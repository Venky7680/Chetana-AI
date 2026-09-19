"""The dashboard config is the one place the browser writes durable JSON.

Keep does not look inside the column, and what one user saves is rendered for
everyone in the tenant, so these tests are about what the console refuses to
store rather than what it accepts.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.allowlist import OPERATIONS, Role, Tier
from app.core.dashboards import DashboardConfig, to_keep_config


def _preset_widget(**overrides):
    widget = {
        "i": "w1",
        "x": 0,
        "y": 0,
        "w": 8,
        "h": 6,
        "static": False,
        "name": "Firing now",
        "widgetType": "PRESET",
        "preset": {"id": "abc", "name": "feed"},
        "presetPanelType": "ALERT_TABLE",
    }
    widget.update(overrides)
    return widget


def _chart_widget(**overrides):
    widget = {
        "i": "w2",
        "x": 8,
        "y": 0,
        "w": 8,
        "h": 6,
        "static": False,
        "name": "Alert volume",
        "widgetType": "GENERICS_METRICS",
        "chetanaChart": {"key": "alert_volume"},
    }
    widget.update(overrides)
    return widget


def test_a_normal_layout_round_trips():
    config = DashboardConfig(widgets=[_preset_widget(), _chart_widget()])
    dumped = to_keep_config(config)
    assert [w["i"] for w in dumped["widgets"]] == ["w1", "w2"]


def test_chart_widgets_carry_none_of_keeps_dispatch_keys():
    """Keep's canvas renders on the presence of preset/metric/genericMetrics.

    A Chetana chart must carry none of them, or Keep will hand it to a renderer
    that cannot read it. Absent, it degrades to an empty card.
    """
    dumped = to_keep_config(DashboardConfig(widgets=[_chart_widget()]))
    widget = dumped["widgets"][0]
    assert not {"preset", "metric", "genericMetrics"} & set(widget)
    assert widget["chetanaChart"] == {"key": "alert_volume"}


def test_preset_widgets_use_keeps_own_field_names():
    dumped = to_keep_config(DashboardConfig(widgets=[_preset_widget()]))
    widget = dumped["widgets"][0]
    assert {"i", "x", "y", "w", "h", "static"} <= set(widget)
    assert widget["presetPanelType"] == "ALERT_TABLE"


# --- what it refuses -------------------------------------------------------
def test_threshold_colour_must_be_a_hex_literal():
    """The colour reaches a style attribute in someone else's browser."""
    with pytest.raises(ValidationError):
        DashboardConfig(
            widgets=[
                _preset_widget(
                    presetPanelType="ALERT_COUNT_PANEL",
                    thresholds=[{"value": 1, "color": "red; background:url(javascript:alert(1))"}],
                )
            ]
        )


def test_custom_link_is_not_accepted_at_all():
    """Keep renders customLink as an href, so a javascript: value is stored XSS."""
    with pytest.raises(ValidationError):
        DashboardConfig(widgets=[_preset_widget(customLink="javascript:alert(1)")])


def test_a_widget_cannot_run_off_the_grid():
    with pytest.raises(ValidationError):
        DashboardConfig(widgets=[_preset_widget(x=20, w=8)])


def test_duplicate_widget_ids_are_rejected():
    with pytest.raises(ValidationError):
        DashboardConfig(widgets=[_preset_widget(), _preset_widget()])


def test_a_widget_must_carry_exactly_one_payload():
    with pytest.raises(ValidationError):
        DashboardConfig(widgets=[_preset_widget(chetanaChart={"key": "alert_volume"})])
    with pytest.raises(ValidationError):
        DashboardConfig(widgets=[_preset_widget(preset=None, presetPanelType=None)])


def test_the_analytics_series_is_a_closed_set():
    """A widget names a series, never a query.

    If it named a query, a saved dashboard would be a way to reach data the
    operation allowlist does not expose.
    """
    with pytest.raises(ValidationError):
        DashboardConfig(widgets=[_chart_widget(chetanaChart={"key": "../../etc/passwd"})])


def test_thresholds_are_refused_where_they_would_be_silently_ignored():
    with pytest.raises(ValidationError):
        DashboardConfig(
            widgets=[_preset_widget(thresholds=[{"value": 5, "color": "#f43f5e"}])]
        )


# --- governance ------------------------------------------------------------
def test_saving_a_dashboard_does_not_require_an_approval_round_trip():
    """Tier 1: it changes nothing in the estate and is undone by editing it back."""
    assert OPERATIONS["dashboards.create"].tier == Tier.AUTO_REVERSIBLE
    assert OPERATIONS["dashboards.update"].tier == Tier.AUTO_REVERSIBLE
    assert OPERATIONS["dashboards.create"].min_role == Role.OPERATOR


def test_deleting_a_dashboard_is_gated():
    """Keep has no undo; the router snapshots the layout to earn tier 2."""
    op = OPERATIONS["dashboards.delete"]
    assert op.tier == Tier.EFFORT_REVERSIBLE
    assert op.min_role >= Role.APPROVER
    assert op.restorable is False
