/**
 * The dashboard layout type, mirroring Keep's `dashboard_config` field for
 * field, and the small amount of geometry both the canvas and the page need.
 *
 * The names here are Keep's, not ours. `i/x/y/w/h/static` is react-grid-layout's
 * LayoutItem; `preset`, `presetPanelType` and `thresholds` are what Keep's own
 * canvas reads. Keeping them identical is what lets a dashboard built in this
 * console open in Keep's canvas without a translation step — and the BFF
 * validates the same shape again before it reaches Keep, because a type is a
 * compile-time promise and the wire is not.
 *
 * `chetanaChart` is the exception, and the exception is the point: Keep's
 * canvas dispatches on the presence of `preset`, `metric` or `genericMetrics`.
 * A widget carrying none of those renders there as an empty card rather than
 * breaking the page, so a Chetana-only widget is safe to store in a config
 * Keep may also read.
 */

export const COLS = 24;
export const ROW_HEIGHT = 30;
export const MARGIN = 10;

export type PresetPanelType = "ALERT_TABLE" | "ALERT_COUNT_PANEL";

/** Closed set, matching the BFF. A widget names a series, never a query. */
export const CHETANA_SERIES = [
  "alert_volume",
  "noisiest_services",
  "severity_breakdown",
  "incidents_by_status",
  "investigation_stats",
  "noise_reduction",
] as const;
export type ChetanaSeries = (typeof CHETANA_SERIES)[number];

export interface Threshold {
  value: number;
  /** #rrggbb only — this reaches a style attribute in every viewer's browser. */
  color: string;
}

export interface Widget {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  minH?: number;
  static: boolean;
  name: string;
  widgetType: "PRESET" | "GENERICS_METRICS";
  preset?: { id: string; name: string };
  presetPanelType?: PresetPanelType;
  showFiringOnly?: boolean;
  thresholds?: Threshold[];
  chetanaChart?: { key: ChetanaSeries };
}

export interface Dashboard {
  id: string;
  dashboard_name: string;
  dashboard_config: { widgets: Widget[] };
}

export function collides(a: Widget, b: Widget): boolean {
  return !(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y);
}

/** Drop a widget below everything already placed. */
export function nextRow(widgets: Widget[]): number {
  return widgets.reduce((max, w) => Math.max(max, w.y + w.h), 0);
}

/**
 * Push overlapping widgets apart, then let everything float up.
 *
 * This is the whole of the grid's behaviour and the part most likely to be
 * subtly wrong, so it lives here as a pure function rather than inside the
 * canvas component: it can be checked without a browser.
 *
 * `pinned` is the widget under the pointer. It holds its cell and the others
 * arrange around it — without that, dragging a widget onto an occupied cell
 * would bounce the dragged widget away instead of the one already there.
 */
export function settle(items: Widget[], pinned?: string): Widget[] {
  const byPosition = (a: Widget, b: Widget) => a.y - b.y || a.x - b.x;

  const first = pinned ? items.filter((w) => w.i === pinned) : [];
  const rest = items.filter((w) => w.i !== pinned).sort(byPosition);

  const placed: Widget[] = first.map((w) => ({ ...w }));
  for (const item of rest) {
    const next = { ...item };
    let moved = true;
    while (moved) {
      moved = false;
      for (const other of placed) {
        if (collides(next, other)) {
          next.y = other.y + other.h;
          moved = true;
        }
      }
    }
    placed.push(next);
  }

  const settled: Widget[] = [];
  for (const item of [...placed].sort(byPosition)) {
    const next = { ...item };
    while (next.y > 0 && !settled.some((o) => collides({ ...next, y: next.y - 1 }, o))) {
      next.y -= 1;
    }
    settled.push(next);
  }
  return settled;
}

export function widgetId(): string {
  return `w${Date.now().toString(36)}${Math.floor(Math.random() * 1e4).toString(36)}`;
}

/** Read a config defensively — it came from a JSON column nothing validates. */
export function widgetsOf(dashboard: Dashboard | null | undefined): Widget[] {
  const raw = dashboard?.dashboard_config?.widgets;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (w): w is Widget =>
      Boolean(w) &&
      typeof w.i === "string" &&
      Number.isFinite(w.x) &&
      Number.isFinite(w.y) &&
      Number.isFinite(w.w) &&
      Number.isFinite(w.h),
  );
}

export const SERIES_LABEL: Record<ChetanaSeries, string> = {
  alert_volume: "Alert volume over time",
  noisiest_services: "Noisiest services",
  severity_breakdown: "Alerts by severity",
  incidents_by_status: "Incidents by status",
  investigation_stats: "Investigation engine",
  noise_reduction: "Noise reduction",
};

export const SERIES_HINT: Record<ChetanaSeries, string> = {
  alert_volume: "Hourly buckets over the sampled window, with the window stated on the axis.",
  noisiest_services: "Top ten by alert count — a tuning list, not an incident list.",
  severity_breakdown: "Counts per severity, labelled rather than stacked.",
  incidents_by_status: "How the open work is distributed.",
  investigation_stats: "Runs, completions, median duration and evidence reads.",
  noise_reduction: "Raw alerts collapsed into incidents a human had to see.",
};

/** The default size each series wants on a 24-column grid. */
export const SERIES_SIZE: Record<ChetanaSeries, { w: number; h: number }> = {
  alert_volume: { w: 16, h: 8 },
  noisiest_services: { w: 8, h: 8 },
  severity_breakdown: { w: 8, h: 8 },
  incidents_by_status: { w: 8, h: 6 },
  investigation_stats: { w: 12, h: 5 },
  noise_reduction: { w: 6, h: 5 },
};

/**
 * The layout a tenant gets on "start from the standard layout".
 *
 * An empty canvas is the problem this whole page had in the first place: it was
 * honest and useless. A new dashboard that already answers the usual questions
 * is something to edit rather than something to start.
 */
export function standardLayout(): Widget[] {
  const place = (key: ChetanaSeries, x: number, y: number): Widget => ({
    i: widgetId(),
    x,
    y,
    ...SERIES_SIZE[key],
    minW: 4,
    minH: 4,
    static: false,
    name: SERIES_LABEL[key],
    widgetType: "GENERICS_METRICS",
    chetanaChart: { key },
  });
  return [
    place("noise_reduction", 0, 0),
    place("investigation_stats", 6, 0),
    place("alert_volume", 0, 5),
    place("severity_breakdown", 16, 5),
    place("noisiest_services", 0, 13),
    place("incidents_by_status", 8, 13),
  ];
}
