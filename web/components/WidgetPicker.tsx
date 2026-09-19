"use client";

import { useState } from "react";
import { BarChart3, Hash, Table2, X } from "lucide-react";
import {
  CHETANA_SERIES,
  SERIES_HINT,
  SERIES_LABEL,
  SERIES_SIZE,
  type ChetanaSeries,
  type Threshold,
  type Widget,
  nextRow,
  widgetId,
} from "@/lib/dashboard";

/**
 * Choosing what to add.
 *
 * Three kinds, because three is what the data supports honestly: a live table
 * from a preset, a single number from a preset with colour thresholds, and one
 * of the analytics series. There is no free-form query widget — see the note in
 * widgets.tsx for why that is a governance property rather than a missing
 * feature.
 */

export interface PresetOption {
  id: string;
  name: string;
  alerts_count?: number;
}

const KINDS = [
  {
    id: "table" as const,
    label: "Alert table",
    hint: "Live rows from a saved preset.",
    icon: Table2,
  },
  {
    id: "count" as const,
    label: "Counter",
    hint: "One number from a preset, coloured by thresholds.",
    icon: Hash,
  },
  {
    id: "chart" as const,
    label: "Analytics",
    hint: "A series computed from this client's own traffic.",
    icon: BarChart3,
  },
];

const DEFAULT_THRESHOLDS: Threshold[] = [
  { value: 0, color: "#22c55e" },
  { value: 10, color: "#facc15" },
  { value: 25, color: "#f43f5e" },
];

export function WidgetPicker({
  presets,
  existing,
  onAdd,
  onClose,
}: {
  presets: PresetOption[];
  existing: Widget[];
  onAdd: (widget: Widget) => void;
  onClose: () => void;
}) {
  const [kind, setKind] = useState<"table" | "count" | "chart">("chart");
  const [presetId, setPresetId] = useState(presets[0]?.id ?? "");
  const [series, setSeries] = useState<ChetanaSeries>("alert_volume");
  const [firingOnly, setFiringOnly] = useState(true);
  const [name, setName] = useState("");

  const preset = presets.find((p) => p.id === presetId);
  const y = nextRow(existing);

  function add() {
    const base = { i: widgetId(), x: 0, y, static: false, minW: 4, minH: 3 };

    if (kind === "chart") {
      onAdd({
        ...base,
        ...SERIES_SIZE[series],
        name: name.trim() || SERIES_LABEL[series],
        widgetType: "GENERICS_METRICS",
        chetanaChart: { key: series },
      });
    } else {
      if (!preset) return;
      onAdd({
        ...base,
        w: kind === "count" ? 6 : 12,
        h: kind === "count" ? 5 : 9,
        name: name.trim() || preset.name,
        widgetType: "PRESET",
        preset: { id: preset.id, name: preset.name },
        presetPanelType: kind === "count" ? "ALERT_COUNT_PANEL" : "ALERT_TABLE",
        showFiringOnly: firingOnly,
        ...(kind === "count" ? { thresholds: DEFAULT_THRESHOLDS } : {}),
      });
    }
    onClose();
  }

  const needsPreset = kind !== "chart";
  const blocked = needsPreset && !preset;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 sm:p-8">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Add a widget"
        className="card w-full max-w-lg"
      >
        <header className="flex items-center justify-between border-b border-surface-border px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-100">Add a widget</h2>
          <button onClick={onClose} aria-label="Close" className="text-slate-500 hover:text-slate-200">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-4 px-5 py-4">
          <div className="grid grid-cols-3 gap-2">
            {KINDS.map((option) => {
              const Icon = option.icon;
              const active = kind === option.id;
              return (
                <button
                  key={option.id}
                  onClick={() => setKind(option.id)}
                  className={`rounded-lg border px-3 py-2.5 text-left transition ${
                    active
                      ? "border-accent bg-accent/10"
                      : "border-surface-border hover:border-slate-600"
                  }`}
                >
                  <Icon className={`h-4 w-4 ${active ? "text-accent" : "text-slate-500"}`} />
                  <p className="mt-1.5 text-xs font-medium text-slate-200">{option.label}</p>
                  <p className="mt-0.5 text-[11px] leading-snug text-slate-600">{option.hint}</p>
                </button>
              );
            })}
          </div>

          {kind === "chart" ? (
            <label className="block">
              <span className="label">Series</span>
              <select
                className="input mt-1"
                value={series}
                onChange={(e) => setSeries(e.target.value as ChetanaSeries)}
              >
                {CHETANA_SERIES.map((key) => (
                  <option key={key} value={key}>
                    {SERIES_LABEL[key]}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-slate-600">{SERIES_HINT[series]}</span>
            </label>
          ) : presets.length === 0 ? (
            <p className="rounded-lg border border-surface-border bg-surface-base px-3 py-2.5 text-xs text-slate-500">
              This client has no saved presets yet, so there is nothing for a preset widget to
              show. Presets are the saved alert filters in the Alerts feed.
            </p>
          ) : (
            <>
              <label className="block">
                <span className="label">Preset</span>
                <select
                  className="input mt-1"
                  value={presetId}
                  onChange={(e) => setPresetId(e.target.value)}
                >
                  {presets.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                      {typeof p.alerts_count === "number" ? ` (${p.alerts_count})` : ""}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center gap-2 text-xs text-slate-400">
                <input
                  type="checkbox"
                  checked={firingOnly}
                  onChange={(e) => setFiringOnly(e.target.checked)}
                  className="h-3.5 w-3.5 accent-accent"
                />
                Count only alerts that are currently firing
              </label>

              {kind === "count" ? (
                <p className="text-xs text-slate-600">
                  Starts with thresholds at 0, 10 and 25. The highest one the count reaches sets
                  the colour.
                </p>
              ) : null}
            </>
          )}

          <label className="block">
            <span className="label">Title</span>
            <input
              className="input mt-1"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
              placeholder={
                kind === "chart" ? SERIES_LABEL[series] : (preset?.name ?? "Widget title")
              }
            />
          </label>
        </div>

        <footer className="flex justify-end gap-2 border-t border-surface-border px-5 py-3">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={add} disabled={blocked}>
            Add widget
          </button>
        </footer>
      </div>
    </div>
  );
}
