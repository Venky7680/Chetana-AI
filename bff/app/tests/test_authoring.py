"""What the console can author without anyone opening Keep.

The product rule is that Keep is the engine and nobody signs into it. Every
test here guards one place that rule had a hole in it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.allowlist import OPERATIONS, Role, Tier
from app.routers.platform import PresetIn


# --- presets ---------------------------------------------------------------
def test_a_preset_is_written_the_way_keep_reads_it():
    """Keep finds the filter by scanning options for a label of "cel".

    Get the label wrong and the preset saves cleanly, appears in the list, and
    silently matches nothing — the worst kind of wrong, because it looks right.
    """
    body = PresetIn(name="Critical payments", cel='severity == "critical"').to_keep()
    assert body["options"] == [{"label": "CEL", "value": 'severity == "critical"'}]
    # Keep lowercases before comparing, so this is the match it performs.
    assert body["options"][0]["label"].lower() == "cel"


def test_keeps_reserved_view_names_are_refused_before_the_round_trip():
    """Keep answers these with a bare 400 and no explanation."""
    for reserved in ("Feed", "feed", "  Deleted  "):
        with pytest.raises(ValidationError):
            PresetIn(name=reserved, cel="")


def test_a_preset_name_is_trimmed_rather_than_stored_with_whitespace():
    assert PresetIn(name="  Unassigned  ", cel="").to_keep()["name"] == "Unassigned"


def test_an_empty_filter_is_allowed():
    """A view of everything is a legitimate view, and Keep accepts it."""
    assert PresetIn(name="All alerts", cel="").to_keep()["options"][0]["value"] == ""


def test_saving_a_view_is_not_gated_but_deleting_one_is():
    """Creating decides what someone is looking at; deleting empties the
    dashboard tiles built on it, in dashboards the deleter may never open."""
    assert OPERATIONS["presets.create"].tier == Tier.AUTO_REVERSIBLE
    assert OPERATIONS["presets.create"].min_role == Role.OPERATOR
    assert OPERATIONS["presets.delete"].tier >= Tier.EFFORT_REVERSIBLE
    assert OPERATIONS["presets.delete"].min_role >= Role.APPROVER


# --- authoring coverage ----------------------------------------------------
def test_every_authorable_domain_can_actually_be_authored():
    """The console is the only way in, so a domain the console can read but
    never write is a dead end that sends someone to Keep's own UI.

    Alerts and incidents arrive from the estate rather than being authored, and
    Keep's AI models are supplied by Keep, so those are reads by nature.
    """
    authorable = {
        "presets",
        "dashboards",
        "topology",
        "rules",
        "dedup",
        "mapping",
        "extraction",
        "maintenance",
        "workflows",
        "providers",
    }
    writable = {
        op_id.split(".")[0] for op_id, op in OPERATIONS.items() if op.is_write
    }
    missing = authorable - writable
    assert not missing, f"no way to author: {sorted(missing)}"


def test_topology_can_be_declared_by_hand_not_only_discovered():
    """Most estates have no provider that exposes a service map, and the
    investigation engine walks this graph to get past the service that is
    merely shouting."""
    for op_id in ("topology.create_service", "topology.create_dependency"):
        assert OPERATIONS[op_id].is_write
