"""The precedent tool hands a language model a body of past resolutions.

The risk is not that it retrieves the wrong ticket. It is that a plausible
retrieval from invented history gets written into a finding as though the estate
had actually seen the problem before. Most of these tests guard that.
"""

from __future__ import annotations

from app.core import evidence as ev
from app.core.corpus_builder import build, merge, redact
from app.core.precedents import CorpusStore, PrecedentIndex

CORPUS = {
    "source": {
        "name": "Test dump",
        "kind": "synthetic",
        "tickets": 5,
        "caveat": "Synthetic data. Treat a match as a hypothesis worth checking.",
    },
    "entries": [
        {
            "symptom": "Azure VM OS disk near capacity",
            "resolution": "Resized OS disk to next tier and extended the volume.",
            "ci_classes": ["AzureVM"],
            "groups": ["Cloud Infrastructure - Azure"],
            "priority": "3 - Moderate",
            "n": 25,
        },
        {
            "symptom": "Printer not responding",
            "resolution": "Print spooler had hung; restarted spooler service.",
            "ci_classes": ["Printer"],
            "groups": ["Service Desk L1"],
            "priority": "4 - Low",
            "n": 33,
        },
        {
            "symptom": "SSL certificate expiring on Cert",
            "resolution": "Renewed certificate through the internal CA.",
            "ci_classes": ["Cert"],
            "groups": ["Security Operations"],
            "priority": "2 - High",
            "n": 17,
        },
    ],
}


def _index() -> PrecedentIndex:
    return PrecedentIndex(CORPUS)


# --- retrieval --------------------------------------------------------------
def test_a_plain_language_symptom_finds_the_right_precedent():
    hits = _index().search("disk is nearly full on the virtual machine", limit=1)
    assert hits and "Resized OS disk" in hits[0]["resolution"]


def test_synonyms_bridge_operator_wording_and_ticket_wording():
    """An alert says "degraded"; a ticket says "slow". Same thing."""
    index = _index()
    assert (
        index.search("printer offline", limit=1)[0]["symptom"]
        == "Printer not responding"
    )


def test_a_ci_class_promotes_rather_than_filters():
    """Filtering would hide the precedent naming the upstream component.

    The service that is shouting is frequently not the one at fault, so a CI
    class weights the ranking and never removes a candidate.
    """
    index = _index()
    hits = index.search("certificate expiry", ci_class="AzureVM", limit=3)
    symptoms = [h["symptom"] for h in hits]
    assert "SSL certificate expiring on Cert" in symptoms


def test_an_unmatchable_query_returns_nothing_rather_than_its_best_guess():
    assert _index().search("xyzzy plugh", limit=5) == []


def test_results_never_carry_a_resolution_duration():
    """The source dump's durations are uniform random — mean equals median,
    skew ~0 — so any MTTR derived from them would be fiction wearing a number.

    `times_seen` is a count of occurrences and is fine; anything measuring
    elapsed time is not, and must not reach the corpus or the payload.
    """
    duration_like = {
        "mttr",
        "resolution_time",
        "duration",
        "hours",
        "elapsed",
        "resolved_in",
    }
    for hit in _index().search("printer", limit=3):
        assert not duration_like & set(hit), f"a duration leaked into {sorted(hit)}"


# --- provenance -------------------------------------------------------------
def test_the_corpus_declares_whether_it_is_real():
    described = _index().describe()
    assert described["kind"] == "synthetic"
    assert "hypothesis" in described["caveat"].lower()


def test_the_tool_tells_the_model_to_repeat_the_provenance():
    """If the description does not say it, nothing downstream will."""
    tool = ev.TOOLS["search_resolution_precedents"]
    assert "synthetic" in tool.description.lower()
    assert "conclusion" in tool.description.lower()


# --- wiring -----------------------------------------------------------------
def test_the_precedent_tool_reaches_no_client_system():
    """Every other evidence tool maps onto an allowlisted read. This one has
    nothing to map onto, and that is the point — there is no estate call to
    scope, and nothing a scoped token could leak."""
    tool = ev.TOOLS["search_resolution_precedents"]
    assert tool.kind == "precedent"
    assert tool.operation_id is None


# --- isolation between clients ---------------------------------------------
def _rows(symptom: str, resolution: str, n: int = 3) -> list[dict[str, str]]:
    return [
        {
            "Short Description": symptom,
            "Resolution Notes": resolution,
            "CI / Affected Resource": "AzureVM-1001",
            "Assignment Group": "Cloud Infrastructure - Azure",
            "Priority": "3 - Moderate",
        }
    ] * n


def test_one_clients_tickets_are_not_searchable_from_another(tmp_path):
    """The failure this guards is not hypothetical.

    Before corpora were per tenant, one file was loaded at startup and every
    investigation searched it. Upload two banks' exports into that and each
    bank's resolutions become citable in the other's incident.
    """
    store = CorpusStore(tmp_path / "corpora")
    store.save(
        "bank-a",
        build(_rows("Core banking batch stalled", "Restarted the settlement service.")),
        upload={"file": "a.csv"},
    )
    store.save(
        "bank-b",
        build(_rows("Branch printer offline", "Restarted the print spooler.")),
        upload={"file": "b.csv"},
    )

    a = store.index("bank-a").search("batch stalled", limit=5)
    b = store.index("bank-b").search("batch stalled", limit=5)
    assert any("settlement" in hit["resolution"] for hit in a)
    assert not any(
        "settlement" in hit["resolution"] for hit in b
    ), "bank-b must not be able to see bank-a's resolutions"


def test_a_tenant_without_an_upload_falls_back_and_the_fallback_says_so(tmp_path):
    shared = tmp_path / "shared.json"
    shared.write_text(
        '{"source": {"kind": "synthetic", "name": "Demo"},'
        ' "entries": [{"symptom": "Printer not responding",'
        ' "resolution": "Restarted spooler.", "n": 4}]}',
        encoding="utf-8",
    )
    store = CorpusStore(tmp_path / "corpora", fallback=shared)

    index = store.index("fresh-client")
    assert index is not None
    # It must announce itself as the demo corpus, not pass for the client's own.
    assert index.describe()["kind"] == "synthetic"
    assert store.corpus("fresh-client") is None


def test_a_tenant_id_that_is_not_a_plain_identifier_is_refused(tmp_path):
    """Tenant ids come from config, not a request — but a path is still a path."""
    store = CorpusStore(tmp_path / "corpora")
    assert store.corpus("../other-client") is None
    assert store.clear("../other-client") is False


def test_no_corpus_anywhere_means_the_tool_is_not_offered(tmp_path):
    store = CorpusStore(tmp_path / "corpora")
    assert store.index("anyone") is None


# --- accumulating exports ---------------------------------------------------
def test_uploads_add_up_rather_than_replace(tmp_path):
    """Loading several years of exports is the point; the second must not
    overwrite the first."""
    first = build(_rows("Printer not responding", "Restarted the print spooler.", n=3))
    second = build(_rows("Printer not responding", "Restarted the print spooler.", n=5))
    merged = merge(first, second)

    assert merged["source"]["tickets"] == 8
    pattern = next(
        e for e in merged["entries"] if e["symptom"] == "Printer not responding"
    )
    assert pattern["n"] == 8, "counts should accumulate across exports"


def test_one_synthetic_export_makes_the_whole_corpus_synthetic():
    """A search result cannot say which upload a pattern came from, so the
    weaker provenance has to win for the corpus as a whole."""
    real = build(_rows("Disk full", "Cleared temp files."), kind="historical")
    fake = build(_rows("Disk full", "Cleared temp files."), kind="synthetic")
    assert merge(real, fake)["source"]["kind"] == "synthetic"
    assert merge(real, real)["source"]["kind"] == "historical"


# --- redaction --------------------------------------------------------------
def test_personal_identifiers_are_stripped_before_anything_is_stored():
    text = "Called Jane Doe on +971 50 123 4567, emailed j.doe@corp.ae about INC1000123"
    cleaned, found = redact(text)
    for leak in ("Jane Doe", "j.doe@corp.ae", "971 50 123", "INC1000123"):
        assert leak not in cleaned, f"{leak!r} survived redaction"
    assert {"name", "email", "phone", "ticket"} <= set(found)


def test_redaction_does_not_eat_the_fix_it_is_meant_to_preserve():
    """Over-redaction is the quieter failure: a corpus of '[name] fixed [name]'
    is useless, and nothing in the system would report it as broken."""
    text = "Restarted the Print Spooler service on the Active Directory member server"
    cleaned, found = redact(text)
    assert cleaned == text
    assert not found


def test_an_ip_address_is_not_reported_as_a_phone_number():
    cleaned, found = redact("Host 10.4.2.88 unreachable")
    assert "[ip]" in cleaned and "phone" not in found


def test_a_built_corpus_carries_no_ticket_identifiers():
    rows = _rows("Server INC1000999 unreachable", "Contacted vendor for Jane Doe.")
    corpus = build(rows)
    blob = str(corpus["entries"])
    assert "INC1000999" not in blob
    assert "Jane Doe" not in blob
