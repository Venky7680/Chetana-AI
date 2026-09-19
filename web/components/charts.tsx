"use client";

import { useId, useState } from "react";

/**
 * Two chart forms, drawn as inline SVG.
 *
 * Deliberately not a charting library: two forms do not justify a dependency,
 * and hand-drawn SVG keeps the marks on the console's own tokens rather than a
 * library's defaults.
 *
 * Colour decisions worth recording, because they were checked rather than
 * chosen. Both forms carry ONE series, so magnitude is encoded by length or
 * height and colour carries no meaning — a single accent hue is correct and
 * needs no legend. Severity is deliberately NOT charted: running the palette
 * validator over the console's severity tokens against the dark surface showed
 * `warning` and `high` at ΔE 14.6 for normal vision, under the 15 floor, so
 * adjacent amber segments in a stacked bar would be genuinely hard to tell
 * apart. Severity is shown as labelled counts instead, where the label carries
 * the identity and the colour is only reinforcement.
 */

/**
 * Marks read from CSS variables, not from literals, so a chart follows the
 * theme instead of assuming a dark ground. The previous fixed hex values were
 * a grid line and a marker ring chosen against #0b1015 — invisible on white.
 *
 * The series colour is deliberately NOT the accent. The accent means "you can
 * act on this"; a line on a chart is not clickable, and using one hue for both
 * teaches people the wrong thing about every other violet in the product.
 */
const SERIES = "rgb(var(--series-1))";
const GRID = "rgb(var(--border))";
const SURFACE = "rgb(var(--raised))";

// ------------------------------------------------------------------ over time
export function VolumeChart({
  points,
  label,
  height = 140,
}: {
  points: { at: string; count: number }[];
  label: string;
  height?: number;
}) {
  const clip = useId();
  const [hover, setHover] = useState<number | null>(null);

  if (points.length === 0) {
    return <p className="py-8 text-center text-sm text-ink-muted">No data in this window.</p>;
  }

  const width = 760;
  const padding = { top: 12, right: 12, bottom: 22, left: 34 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;
  const max = Math.max(...points.map((p) => p.count), 1);

  const x = (i: number) =>
    padding.left + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
  const y = (v: number) => padding.top + plotH - (v / max) * plotH;

  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.count)}`).join(" ");
  const area = `${line} L${x(points.length - 1)},${padding.top + plotH} L${x(0)},${padding.top + plotH} Z`;

  const ticks = [0, Math.round(max / 2), max];
  const active = hover !== null ? points[hover] : null;

  return (
    <figure className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label={`${label}. Peak ${max} in one bucket.`}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={clip} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SERIES} stopOpacity="0.28" />
            <stop offset="100%" stopColor={SERIES} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Recessive grid — present enough to read a value against, quiet
            enough not to compete with the mark. */}
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={y(t)}
              y2={y(t)}
              stroke={GRID}
              strokeWidth="1"
            />
            <text x={padding.left - 8} y={y(t) + 3.5} textAnchor="end" className="fill-ink-muted text-[10px]">
              {t}
            </text>
          </g>
        ))}

        <path d={area} fill={`url(#${clip})`} />
        <path d={line} fill="none" stroke={SERIES} strokeWidth="2" strokeLinejoin="round" />

        {active ? (
          <>
            <line
              x1={x(hover!)}
              x2={x(hover!)}
              y1={padding.top}
              y2={padding.top + plotH}
              stroke={GRID}
              strokeWidth="1"
            />
            {/* 2px surface ring so the marker reads against the area fill. */}
            <circle cx={x(hover!)} cy={y(active.count)} r="4.5" fill={SERIES} stroke={SURFACE} strokeWidth="2" />
          </>
        ) : null}

        {/* Hit targets are far wider than the marks they select. */}
        {points.map((p, i) => (
          <rect
            key={p.at}
            x={x(i) - plotW / points.length / 2}
            y={padding.top}
            width={Math.max(plotW / points.length, 6)}
            height={plotH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>

      {active ? (
        <div className="pointer-events-none absolute left-0 top-0 rounded-md border border-surface-border bg-surface-overlay px-2.5 py-1.5 text-xs shadow-lg">
          <span className="font-medium text-ink">{active.count}</span>
          <span className="text-ink-muted"> alerts · </span>
          <span className="text-ink-2">
            {new Date(active.at).toLocaleString(undefined, {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
      ) : null}
      <figcaption className="mt-1 text-xs text-ink-muted">{label}</figcaption>
    </figure>
  );
}

// ------------------------------------------------------------------ ranking
export function BarList({
  items,
  unit = "alerts",
}: {
  items: { name: string; count: number }[];
  unit?: string;
}) {
  if (items.length === 0) {
    return <p className="py-8 text-center text-sm text-ink-muted">Nothing to rank yet.</p>;
  }
  const max = Math.max(...items.map((i) => i.count), 1);

  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.name} className="group">
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-sm text-ink-2">{item.name}</span>
            {/* Value as text, in ink — never coloured to match the bar. */}
            <span className="shrink-0 tabular-nums text-xs text-ink-muted">
              {item.count.toLocaleString()} {unit}
            </span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-overlay">
            <div
              className="h-full rounded-full transition-[width]"
              style={{ width: `${Math.max((item.count / max) * 100, 2)}%`, background: SERIES }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
