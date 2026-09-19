"use client";

import { useMemo, useState } from "react";
import { ChevronDown, Plus, RotateCcw } from "lucide-react";

export interface Facet {
  key: string;
  label: string;
  options: { value: string; count: number }[];
}

export type FacetSelection = Record<string, string[]>;

/**
 * Keep's facet sidebar, rebuilt in Chetana's own language.
 *
 * Counts come from the BFF, computed over everything Keep returned, so they do
 * not shift as you tick boxes — the count next to "critical" always means "how
 * many critical there are", never "how many are left after my other filters".
 */
export function FacetSidebar({
  facets,
  selection,
  onChange,
  loading,
}: {
  facets: Facet[];
  selection: FacetSelection;
  onChange: (next: FacetSelection) => void;
  loading?: boolean;
}) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const active = useMemo(
    () => Object.values(selection).reduce((n, v) => n + v.length, 0),
    [selection],
  );

  function toggle(key: string, value: string) {
    const current = selection[key] ?? [];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    const merged = { ...selection, [key]: next };
    if (next.length === 0) delete merged[key];
    onChange(merged);
  }

  function only(key: string, value: string) {
    onChange({ ...selection, [key]: [value] });
  }

  return (
    <aside className="w-56 shrink-0 space-y-4">
      <div className="flex items-center justify-between">
        <span className="label">Filters</span>
        {active > 0 ? (
          <button
            onClick={() => onChange({})}
            className="inline-flex items-center gap-1 text-xs text-slate-500 transition hover:text-accent"
          >
            <RotateCcw className="h-3 w-3" />
            Reset
          </button>
        ) : null}
      </div>

      {loading && facets.length === 0 ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-surface-overlay/60" />
          ))}
        </div>
      ) : null}

      {facets.map((facet) => {
        const isCollapsed = collapsed[facet.key];
        const chosen = selection[facet.key] ?? [];
        return (
          <div key={facet.key} className="border-b border-surface-border/70 pb-3 last:border-0">
            <button
              onClick={() => setCollapsed({ ...collapsed, [facet.key]: !isCollapsed })}
              className="flex w-full items-center justify-between py-1 text-left"
            >
              <span className="text-xs font-medium text-slate-300">{facet.label}</span>
              <ChevronDown
                className={`h-3.5 w-3.5 text-slate-600 transition ${isCollapsed ? "-rotate-90" : ""}`}
              />
            </button>

            {!isCollapsed ? (
              <ul className="mt-1 space-y-0.5">
                {facet.options.length === 0 ? (
                  <li className="py-1 text-xs text-slate-600">none</li>
                ) : (
                  facet.options.slice(0, 12).map((option) => {
                    const checked = chosen.includes(option.value);
                    return (
                      <li key={option.value} className="group flex items-center gap-2">
                        <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 py-0.5">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggle(facet.key, option.value)}
                            className="h-3.5 w-3.5 shrink-0 rounded border-surface-border bg-surface-base accent-accent"
                          />
                          <span
                            className={`truncate text-xs ${
                              checked ? "text-slate-200" : "text-slate-400"
                            }`}
                            title={option.value}
                          >
                            {option.value}
                          </span>
                        </label>
                        <button
                          onClick={() => only(facet.key, option.value)}
                          title={`Only ${option.value}`}
                          className="hidden text-[10px] uppercase text-slate-600 hover:text-accent group-hover:block"
                        >
                          only
                        </button>
                        <span className="shrink-0 tabular-nums text-xs text-slate-600">
                          {option.count}
                        </span>
                      </li>
                    );
                  })
                )}
                {facet.options.length > 12 ? (
                  <li className="flex items-center gap-1 pt-1 text-[11px] text-slate-600">
                    <Plus className="h-3 w-3" />
                    {facet.options.length - 12} more
                  </li>
                ) : null}
              </ul>
            ) : null}
          </div>
        );
      })}
    </aside>
  );
}

/** Apply a facet selection to rows. A facet with nothing ticked is inert. */
export function applyFacets<T>(
  rows: T[],
  selection: FacetSelection,
  valueOf: (row: T, key: string) => string | string[],
): T[] {
  const active = Object.entries(selection).filter(([, values]) => values.length > 0);
  if (active.length === 0) return rows;

  return rows.filter((row) =>
    active.every(([key, wanted]) => {
      const value = valueOf(row, key);
      const values = (Array.isArray(value) ? value : [value]).map((v) =>
        v === null || v === undefined || v === "" ? "None" : String(v),
      );
      if (values.length === 0) return wanted.includes("None");
      return values.some((v) => wanted.includes(v));
    }),
  );
}
