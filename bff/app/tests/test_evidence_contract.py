"""Pure-unit tests for the evidence contract.

These do not need a running app: they assert the properties the whole design
rests on, so that breaking one fails fast and unmistakably.
"""

from __future__ import annotations

import jwt
import pytest

from app.core import evidence as ev
from app.core.allowlist import Tier, get_operation

SECRET = "test-secret"


def _token(
    *,
    investigation_id: str,
    tenant_id: str = "almasraf",
    tools: tuple[str, ...] | None = None,
    ttl: int = 300,
) -> str:
    return ev.mint_token(
        secret=SECRET,
        algorithm="HS256",
        investigation_id=investigation_id,
        tenant_id=tenant_id,
        tools=tools if tools is not None else ev.ALL_TOOL_NAMES,
        ttl_seconds=ttl,
    )


def test_every_evidence_tool_is_read_only():
    """The entire safety argument rests on this. A future edit that points an
    evidence tool at a write operation must fail loudly, not ship."""
    for tool in ev.TOOLS.values():
        if tool.operation_id is None:
            continue
        operation = get_operation(tool.operation_id)
        assert operation.tier == Tier.READ_ONLY, tool.name
        assert not operation.is_write, tool.name


def test_evidence_token_round_trip():
    grant = ev.verify_token(
        secret=SECRET, algorithm="HS256", token=_token(investigation_id="inv_x")
    )
    assert grant.investigation_id == "inv_x"
    assert grant.tenant_id == "almasraf"
    assert grant.permits("get_incident")
    assert not grant.permits("delete_everything")


def test_expired_evidence_token_is_rejected():
    token = ev.mint_token(
        secret=SECRET,
        algorithm="HS256",
        investigation_id="inv_x",
        tenant_id="almasraf",
        tools=ev.ALL_TOOL_NAMES,
        ttl_seconds=-5,
    )
    with pytest.raises(ev.EvidenceTokenError):
        ev.verify_token(secret=SECRET, algorithm="HS256", token=token)


def test_a_console_session_token_is_not_an_evidence_token():
    """The two token families are deliberately not interchangeable: a stolen
    console session must not become estate access for an LLM, and vice versa."""
    console = jwt.encode(
        {"sub": "operator@intertecsys.com", "role": "admin", "iss": "chetana-bff"},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(ev.EvidenceTokenError):
        ev.verify_token(secret=SECRET, algorithm="HS256", token=console)




# --------------------------------------------------------------- data horizon
#
# A range query that outruns metric retention comes back silently truncated:
# Prometheus returns 200 with whatever it has. The oldest returned sample then
# looks like the beginning of history, so "the metric was healthy beforehand"
# and "we have no data from beforehand" become indistinguishable — which is how
# an investigation cites the edge of retention as proof of precedence.
import time  # noqa: E402

from app.routers.evidence import _series_extent, _with_data_horizon  # noqa: E402


def _matrix(*offsets_seconds: float) -> dict:
    now = time.time()
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {"metric": {}, "values": [[now - o, "1"] for o in sorted(offsets_seconds, reverse=True)]}
            ],
        },
    }


def test_truncated_window_is_flagged():
    now = time.time()
    payload = _matrix(6 * 3600, 0)  # asked for 20h, only 6h exists
    horizon = _with_data_horizon(payload, now - 20 * 3600, now)["data_horizon"]
    assert horizon["truncated"] is True
    assert "retention" in horizon["warning"]
    # It must say plainly that the oldest sample is not the start of the problem.
    assert "NOT the moment the behaviour began" in horizon["warning"]


def test_complete_window_is_not_flagged():
    now = time.time()
    horizon = _with_data_horizon(_matrix(3600, 0), now - 3600, now)["data_horizon"]
    assert horizon["truncated"] is False
    assert "warning" not in horizon


def test_empty_result_warns_rather_than_implying_health():
    now = time.time()
    payload = {"status": "success", "data": {"resultType": "matrix", "result": []}}
    horizon = _with_data_horizon(payload, now - 3600, now)["data_horizon"]
    assert horizon["data_from"] is None
    assert "healthy" in horizon["warning"]


def test_the_original_payload_is_preserved():
    now = time.time()
    payload = _matrix(600, 0)
    wrapped = _with_data_horizon(payload, now - 600, now)
    assert wrapped["result"] is payload


def test_series_extent_survives_malformed_samples():
    assert _series_extent({"data": {"result": [{"values": [["nope", "1"]]}]}}) == (None, None)
    assert _series_extent({"data": {"result": "not-a-list"}}) == (None, None)
    assert _series_extent({}) == (None, None)
