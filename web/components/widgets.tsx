"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { BarList, VolumeChart } from "@/components/charts";
import { SeverityBadge } from "@/components/ui";
import type { ChetanaSeries, Threshold, Widget } from "@/lib/dashboard";

/**
 * What a tile actually draws.
 *
 * Every widget reads through the BFF, so a dashboard can only ever show data
 * the operation allowlist already exposes. There is no widget that takes a
 * query: a chart names a series and a preset widget names a preset, which
 * means a saved layout cannot become a way to reach something the console
 * would otherwise refuse.
 */

export interface Analytics {
  stats: {
    alerts_total: number;
    alerts_firing: number;
    incidents_total: number;
    incidents_open: number;
    alerts_correlated: number;
    noise_reduction_pct: number;
    unassigned_incidents: number;
    critical_open: number;
    alerts_by_severity: Record<string, number>;
  };
  window: { from: string | null; to: string | null; alerts_sampled: number };
  alert_volume: { at: string; count: number }[];
  noisiest_services: { name: string; count: number }[];
  incidents_by_status: Record<string, number>;
  investigations: {
    total: number;
    complete?: number;
    failed?: number;
    evidence_reads?: number;
    median_seconds?: number | null;
  };
  problems?: string[];
}

const SEVERITY_ORDER = ["critical", "high", "warning", "low", "info"];

function windowLabel(window: Analytics["window"]): string {
  if (!window.from || !window.to) return "No alerts in range";
  const from = new Date(window.from);
  const to = new Date(window.to);
  const hours = Math.max(1, Math.round((to.getTime() - from.getTime()) / 3_600_000));
  return `Alerts per hour · last ${hours}h · ${window.alerts_sampled} sampled`;
}

function Figure({ value, hint, tone }: { value: string | number; hint?: string; tone?: string }) {
  return (
    <div className="flex h-full flex-col justify-center">
      <p className={`text-3xl font-semibold tabular-nums ${tone ?? "text-slate-100"}`}>{value}</p>
      {hint ? <p className="mt-1 text-xs text-slate-500">{hint}</p> : null}
    </div>
  );
}

function Pairs({ rows }: { rows: [string, number][] }) {
  if (rows.length === 0) {
    return <p className="py-6 text-center text-sm text-slate-600">Nothing in this window.</p>;
  }
  return (
    <ul className="space-y-1.5">
      {rows.map(([label, count]) => (
        <li key={label} className="flex items-center justify-between gap-3 text-sm">
          <span className="capitalize text-slate-400">{label}</span>
          <span className="tabular-nums text-slate-300">{count.toLocaleString()}</span>
        </li>
      ))}
    </ul>
  );
}

// ------------------------------------------------------------ analytics tile
export function ChetanaChartWidget({
  series,
  analytics,
}: {
  series: ChetanaSeries;
  analytics: Analytics | null;
}) {
  if (!analytics) return <p className="text-xs text-slate-600">Loading…</p>;
  const { stats, investigations } = analytics;

  switch (series) {
    case "alert_volume":
      return <VolumeChart points={analytics.alert_volume ?? []} label={windowLabel(analytics.window)} />;

    case "noisiest_services":
      return <BarList items={analytics.noisiest_services ?? []} />;

    case "severity_breakdown": {
      const rows = SEVERITY_ORDER.filter((s) => (stats.alerts_by_severity?.[s] ?? 0) > 0);
      if (rows.length === 0) {
        return <p className="py-6 text-center text-sm text-slate-600">No alerts in this window.</p>;
      }
      // Labelled counts rather than a stacked bar: two of the severity tokens
      // sit at ΔE 14.6 for normal vision, under the 15 floor, so adjacent
      // segments would not be reliably distinguishable. The label carries it.
      return (
        <ul className="space-y-2">
          {rows.map((severity) => (
            <li key={severity} className="flex items-center justify-between gap-3">
              <SeverityBadge severity={severity} />
              <span className="tabular-nums text-sm text-slate-300">
                {(stats.alerts_by_severity[severity] ?? 0).toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      );
    }

    case "incidents_by_status":
      return (
        <Pairs
          rows={Object.entries(analytics.incidents_by_status ?? {}).sort((a, b) => b[1] - a[1])}
        />
      );

    case "noise_reduction":
      return (
        <Figure
          value={`${stats.noise_reduction_pct}%`}
          hint={`${stats.alerts_correlated} alerts → ${stats.incidents_total} incidents`}
          tone={stats.noise_reduction_pct > 0 ? "text-emerald-400" : undefined}
        />
      );

    case "investigation_stats":
      return (
        <div className="grid h-full grid-cols-2 items-center gap-3 lg:grid-cols-4">
          <Figure value={investigations.total} hint="run" />
          <Figure value={investigations.complete ?? 0} hint="completed" />
          <Figure
            value={investigations.median_seconds ? `${investigations.median_seconds}s` : "—"}
            hint="median"
          />
          <Figure value={(investigations.evidence_reads ?? 0).toLocaleString()} hint="evidence reads" />
        </div>
      );

    default:
      return <p className="text-xs text-slate-600">Unknown series.</p>;
  }
}

// -------------------------------------------------------------- preset tiles
interface PresetAlert {
  id?: string;
  fingerprint?: string;
  name?: string;
  severity?: string;
  status?: string;
  service?: string;
  lastReceived?: string;
}

/** Cache per preset name for the life of the page: many tiles, one preset. */
const alertCache = new Map<string, Promise<PresetAlert[]>>();

function loadPresetAlerts(name: string): Promise<PresetAlert[]> {
  let pending = alertCache.get(name);
  if (!pending) {
    pending = api<{ items: PresetAlert[] }>(
      `/dashboards/preset-alerts/${encodeURIComponent(name)}`,
      { query: { limit: 50 } },
    )
      .then((r) => (Array.isArray(r.items) ? r.items : []))
      .catch(() => []);
    alertCache.set(name, pending);
  }
  return pending;
}

export function clearPresetCache() {
  alertCache.clear();
}

function usePresetAlerts(name: string | undefined) {
  const [rows, setRows] = useState<PresetAlert[] | null>(null);
  useEffect(() => {
    if (!name) return;
    let live = true;
    loadPresetAlerts(name).then((r) => live && setRows(r));
    return () => {
      live = false;
    };
  }, [name]);
  return rows;
}

export function PresetTableWidget({ widget }: { widget: Widget }) {
  const rows = usePresetAlerts(widget.preset?.name);
  if (rows === null) return <p className="text-xs text-slate-600">Loading…</p>;

  const shown = widget.showFiringOnly
    ? rows.filter((a) => (a.status ?? "").toLowerCase() === "firing")
    : rows;

  if (shown.length === 0) {
    return <p className="py-6 text-center text-sm text-slate-600">Nothing matching right now.</p>;
  }

  return (
    <table className="w-full">
      <tbody>
        {shown.map((alert, index) => (
          <tr key={alert.fingerprint ?? alert.id ?? index} className="row">
            <td className="td">
              <p className="truncate text-sm text-slate-200">{alert.name ?? "—"}</p>
              {alert.service ? (
                <p className="truncate text-xs text-slate-600">{alert.service}</p>
              ) : null}
            </td>
            <td className="td w-24 text-right">
              {alert.severity ? <SeverityBadge severity={alert.severity} /> : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Highest threshold at or below the count wins; none means default ink. */
export function thresholdColour(count: number, thresholds: Threshold[] | undefined): string | undefined {
  if (!thresholds?.length) return undefined;
  const hit = [...thresholds]
    .filter((t) => Number.isFinite(t.value) && count >= t.value)
    .sort((a, b) => b.value - a.value)[0];
  return hit?.color;
}

export function PresetCountWidget({ widget }: { widget: Widget }) {
  const rows = usePresetAlerts(widget.preset?.name);
  if (rows === null) return <p className="text-xs text-slate-600">Loading…</p>;

  const counted = widget.showFiringOnly
    ? rows.filter((a) => (a.status ?? "").toLowerCase() === "firing")
    : rows;
  const colour = thresholdColour(counted.length, widget.thresholds);

  return (
    <div className="flex h-full flex-col justify-center">
      <p
        className="text-4xl font-semibold tabular-nums text-slate-100"
        style={colour ? { color: colour } : undefined}
      >
        {counted.length}
      </p>
      <p className="mt-1 truncate text-xs text-slate-500">
        {widget.preset?.name}
        {widget.showFiringOnly ? " · firing only" : ""}
      </p>
    </div>
  );
}
