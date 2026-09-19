"""The schema for dashboard layouts the console writes into Keep.

Keep stores `dashboard_config` as an opaque JSON column and validates nothing
inside it — its own frontend is the only thing that has ever defined the shape.
That makes this module the boundary: whatever the browser posts becomes a
durable record in Keep's database and is later rendered, by this console and
potentially by Keep's own canvas, for every user of the tenant.

Three things follow from that, and each one is a rule below rather than a
convention:

  * **The field names are Keep's, exactly.** `i/x/y/w/h/static` for geometry,
    `preset` + `presetPanelType` + `thresholds` for a preset widget. Keep's
    canvas dispatches on the *presence* of `preset`, `metric` or
    `genericMetrics`, so a widget written here renders there unchanged.

  * **A Chetana-only widget carries none of those three keys.** It uses
    `chetanaChart`, which Keep's canvas does not look for, so an analytics
    widget degrades to an empty titled card in Keep instead of breaking the
    page. That is the whole reason it is not squeezed into `genericMetrics`.

  * **Threshold colours must be hex literals.** The colour is interpolated
    into a style attribute in the browser. A stored dashboard is written by
    one user and rendered for all of them, so an unconstrained string here is
    a stored-injection vector, not a styling choice.

`customLink` is deliberately not accepted. Keep renders it as an href, and a
`javascript:` value in a shared dashboard is the same vector by another route.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# Keep's grid: 24 columns at the large breakpoint, 30px rows.
GRID_COLUMNS = 24
MAX_WIDGETS = 60
MAX_ROWS = 400

HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
WIDGET_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# The analytics series this console can render. A closed set on purpose: the
# widget names a series, never a query, so a saved dashboard cannot be used to
# reach data the operation allowlist does not already expose.
CHETANA_SERIES = frozenset(
    {
        "alert_volume",
        "noisiest_services",
        "severity_breakdown",
        "incidents_by_status",
        "investigation_stats",
        "noise_reduction",
    }
)


class Threshold(BaseModel):
    model_config = {"extra": "forbid"}

    value: float = Field(ge=0)
    color: str

    @model_validator(mode="after")
    def _colour_is_a_hex_literal(self) -> Threshold:
        if not HEX_COLOUR.match(self.color):
            raise ValueError(
                f"threshold colour must be a #rrggbb literal, got {self.color!r}"
            )
        return self


class PresetRef(BaseModel):
    """Only what the renderer needs to fetch the preset's alerts.

    Keep's own config embeds the whole preset object. Storing a copy of it
    would mean every dashboard holds a snapshot that silently goes stale the
    moment someone edits the preset, so this keeps the reference and resolves
    it at render time.
    """

    model_config = {"extra": "ignore"}

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)


class ChetanaChart(BaseModel):
    model_config = {"extra": "forbid"}

    key: str

    @model_validator(mode="after")
    def _series_is_known(self) -> ChetanaChart:
        if self.key not in CHETANA_SERIES:
            raise ValueError(
                f"unknown analytics series {self.key!r}; "
                f"expected one of {', '.join(sorted(CHETANA_SERIES))}"
            )
        return self


class Widget(BaseModel):
    """One tile. Geometry is Keep's LayoutItem; the payload picks the renderer."""

    model_config = {"extra": "forbid"}

    # --- geometry (Keep's LayoutItem, field for field) ---
    i: str
    x: int = Field(ge=0, le=GRID_COLUMNS - 1)
    y: int = Field(ge=0, le=MAX_ROWS)
    w: int = Field(ge=1, le=GRID_COLUMNS)
    h: int = Field(ge=1, le=80)
    minW: int | None = Field(default=None, ge=1, le=GRID_COLUMNS)
    minH: int | None = Field(default=None, ge=1, le=80)
    static: bool = False

    # --- presentation ---
    name: str = Field(min_length=1, max_length=120)
    widgetType: Literal["PRESET", "GENERICS_METRICS"]

    # --- payload: exactly one ---
    preset: PresetRef | None = None
    presetPanelType: Literal["ALERT_TABLE", "ALERT_COUNT_PANEL"] | None = None
    showFiringOnly: bool = False
    thresholds: list[Threshold] = Field(default_factory=list, max_length=8)
    chetanaChart: ChetanaChart | None = None

    @model_validator(mode="after")
    def _coherent(self) -> Widget:
        if not WIDGET_ID.match(self.i):
            raise ValueError(f"widget id {self.i!r} must be short and alphanumeric")
        if self.x + self.w > GRID_COLUMNS:
            raise ValueError(
                f"widget {self.i!r} runs off the grid: x={self.x} + w={self.w} > {GRID_COLUMNS}"
            )

        payloads = [p for p in (self.preset, self.chetanaChart) if p is not None]
        if len(payloads) != 1:
            raise ValueError(f"widget {self.i!r} must carry exactly one payload")

        if self.preset is not None:
            if self.widgetType != "PRESET":
                raise ValueError(f"widget {self.i!r} has a preset but widgetType {self.widgetType}")
            if self.presetPanelType is None:
                raise ValueError(f"widget {self.i!r} must say which preset panel to render")
            # Thresholds colour a single number. On a table they would have
            # nothing to colour, and silently ignoring them would leave the
            # author believing they had been saved.
            if self.thresholds and self.presetPanelType != "ALERT_COUNT_PANEL":
                raise ValueError(f"widget {self.i!r}: thresholds only apply to a count panel")
        else:
            if self.widgetType != "GENERICS_METRICS":
                raise ValueError(
                    f"widget {self.i!r} is an analytics chart but widgetType {self.widgetType}"
                )
            if self.presetPanelType is not None or self.thresholds:
                raise ValueError(f"widget {self.i!r} carries preset fields it cannot use")

        return self


class DashboardConfig(BaseModel):
    model_config = {"extra": "forbid"}

    widgets: list[Widget] = Field(default_factory=list, max_length=MAX_WIDGETS)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> DashboardConfig:
        seen = [w.i for w in self.widgets]
        if len(set(seen)) != len(seen):
            raise ValueError("two widgets share an id; the grid would drop one of them")
        return self


def to_keep_config(config: DashboardConfig) -> dict[str, Any]:
    """Serialise for Keep.

    `exclude_none` keeps `preset`/`chetanaChart` genuinely absent rather than
    present-and-null, because Keep's canvas dispatches on truthiness of those
    keys — a null would be falsy today but the intent is clearer as absence.
    """
    return config.model_dump(exclude_none=True)
