from __future__ import annotations

import pytest

from app.core.allowlist import OPERATIONS, Role, Tier, get_operation
from app.core.autonomy import approvals_required_for, effective_ceiling, evaluate
from app.core.keep_client import filter_query, render_path


def test_every_operation_declares_its_path_params():
    """A template placeholder that is not declared would produce a broken URL."""
    for op in OPERATIONS.values():
        placeholders = {
            seg[1:-1] for seg in op.path.split("/") if seg.startswith("{") and seg.endswith("}")
        }
        assert placeholders == set(op.path_params), op.id


def test_destructive_operations_are_tier_three_and_admin_only():
    for op in OPERATIONS.values():
        if op.method == "DELETE" and op.tier == Tier.IRREVERSIBLE:
            assert op.min_role == Role.ADMIN, op.id
        # Nothing destructive may sit below tier 2 unless it is explicitly
        # flagged as restorable (ending a state, not destroying a record).
        if op.method == "DELETE" and not op.restorable:
            assert op.tier >= Tier.EFFORT_REVERSIBLE, op.id


def test_read_operations_are_tier_zero():
    for op in OPERATIONS.values():
        if not op.is_write:
            assert op.tier == Tier.READ_ONLY, op.id


def test_render_path_encodes_and_requires_params():
    op = get_operation("alerts.get")
    assert render_path(op, {"fingerprint": "abc/def"}) == "/alerts/abc%2Fdef"
    with pytest.raises(ValueError):
        render_path(op, {})


def test_filter_query_drops_undeclared_params():
    op = get_operation("alerts.list")
    filtered = filter_query(op, {"limit": 10, "evil": "1", "cel": "", "offset": None})
    assert filtered == {"limit": 10}


def test_ceiling_is_the_strictest_of_global_and_tenant():
    assert effective_ceiling(3, 1) == Tier.AUTO_REVERSIBLE
    assert effective_ceiling(0, 3) == Tier.READ_ONLY


@pytest.mark.parametrize(
    "tier,expected",
    [(Tier.READ_ONLY, 0), (Tier.AUTO_REVERSIBLE, 0), (Tier.EFFORT_REVERSIBLE, 1), (Tier.IRREVERSIBLE, 2)],
)
def test_approval_counts_scale_with_irreversibility(tier, expected):
    assert approvals_required_for(tier) == expected


def test_gate_denies_below_role_before_considering_tier():
    result = evaluate(
        operation=get_operation("incidents.delete"),
        role=Role.OPERATOR,
        global_max=3,
        tenant_max=3,
    )
    assert result.decision == "denied"


def test_gate_parks_when_tier_exceeds_ceiling():
    result = evaluate(
        operation=get_operation("workflows.run"),
        role=Role.OPERATOR,
        global_max=1,
        tenant_max=1,
    )
    assert result.decision == "approval_required"
    assert result.approvals_needed == 1


def test_gate_executes_within_ceiling():
    result = evaluate(
        operation=get_operation("workflows.run"),
        role=Role.OPERATOR,
        global_max=2,
        tenant_max=2,
    )
    assert result.decision == "execute"


def test_read_is_never_gated_even_at_ceiling_zero():
    result = evaluate(
        operation=get_operation("alerts.list"), role=Role.VIEWER, global_max=0, tenant_max=0
    )
    assert result.decision == "execute"


def test_config_files_written_by_windows_powershell_are_readable(tmp_path):
    """PowerShell 5.1's `Set-Content -Encoding UTF8` prepends a UTF-8 BOM.

    Read as plain utf-8 that is a hard JSONDecodeError at startup, which is how
    a correctly configured deployment ends up refusing every sign-in with
    'Failed to fetch' and no clue why.
    """
    import json

    from app.core.config import Settings

    payload = [{"id": "x", "name": "X", "keep_base_url": "http://k", "keep_api_key": "k"}]
    path = tmp_path / "tenants.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))

    assert Settings._load_json(str(path)) == payload
    # And an inline value carrying a BOM.
    assert Settings._load_json("﻿" + json.dumps(payload)) == payload


def test_malformed_config_names_the_file(tmp_path):
    from app.core.config import Settings

    path = tmp_path / "users.json"
    path.write_text("{not json", encoding="utf-8")
    try:
        Settings._load_json(str(path))
    except ValueError as exc:
        assert "users.json" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a ValueError naming the file")


# --- credentials -----------------------------------------------------------
def test_operations_taking_credentials_are_marked():
    """The protections key off `secret_body`, so the flag is the contract.

    If a future operation starts accepting credentials without it, nothing else
    in the BFF will know to protect them.
    """
    assert OPERATIONS["providers.install"].secret_body is True
    assert OPERATIONS["providers.test"].secret_body is True
    # And the flag only belongs on operations that actually carry a secret.
    flagged = {op.id for op in OPERATIONS.values() if op.secret_body}
    assert flagged == {"providers.install", "providers.test"}
