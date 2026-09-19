"use client";

import { useState } from "react";
import { Bookmark, Check, Plus, Trash2, X } from "lucide-react";
import { useAction } from "@/lib/useAction";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import type { Preset } from "@/lib/types";

/**
 * Saved alert views — Keep calls them presets.
 *
 * These used to render as inert chips labelled "defined in Keep", which was an
 * accurate description of a dead end: the only way to get one was to log into
 * Keep, and dashboards cannot show a preset tile for a preset nobody can make.
 *
 * A preset is a name plus a CEL expression, and the feed above is already
 * filtered by CEL — so saving one is just naming the filter that is on screen.
 * That is why there is no separate "new view" form: the filter *is* the form.
 */

/** Keep stores the filter as an option row; the label match is case-insensitive. */
export function celOf(preset: Preset): string {
  const option = (preset.options ?? []).find(
    (o) => (o.label ?? "").toLowerCase() === "cel",
  );
  return typeof option?.value === "string" ? option.value : "";
}

export function SavedViews({
  presets,
  currentCel,
  activeCel,
  onApply,
  onChanged,
}: {
  presets: Preset[];
  /** What is in the filter box right now — this is what gets saved. */
  currentCel: string;
  /** What is actually applied, so the matching view can be marked. */
  activeCel: string;
  onApply: (cel: string) => void;
  onChanged: () => void;
}) {
  const action = useAction();
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");

  const trimmed = currentCel.trim();
  const already = presets.some((p) => celOf(p) === trimmed);

  async function save() {
    const clean = name.trim();
    if (!clean) return;
    const saved = await action.run("/presets", {
      body: { name: clean, cel: trimmed, counter_shows_firing_only: true },
      successMessage: "View saved",
    });
    if (!saved) return; // parked or failed — the banner below says which
    setNaming(false);
    setName("");
    onChanged();
  }

  async function remove(preset: Preset) {
    const done = await action.run(`/presets/${encodeURIComponent(preset.id)}`, {
      method: "DELETE",
      successMessage: "View deleted",
    });
    if (done === null && action.parked) return;
    onChanged();
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="label mr-1 inline-flex items-center gap-1.5">
          <Bookmark className="h-3 w-3" />
          Saved views
        </span>

        {presets.length === 0 ? (
          <span className="text-xs text-slate-600">
            None yet — filter the feed, then save it.
          </span>
        ) : null}

        {presets.map((preset) => {
          const cel = celOf(preset);
          const active = Boolean(cel) && cel === activeCel;
          return (
            <span
              key={preset.id}
              className={`inline-flex items-center overflow-hidden rounded-md border text-xs transition ${
                active
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-surface-border text-slate-400 hover:border-slate-500"
              }`}
            >
              <button
                onClick={() => onApply(cel)}
                title={cel || "This view has no CEL filter"}
                className="px-2 py-1"
              >
                {preset.name}
                {typeof preset.alerts_count === "number" ? (
                  <span className="ml-1.5 tabular-nums opacity-60">{preset.alerts_count}</span>
                ) : null}
              </button>
              <button
                onClick={() => remove(preset)}
                aria-label={`Delete the ${preset.name} view`}
                disabled={action.busy}
                className="border-l border-inherit px-1.5 py-1 opacity-50 transition hover:text-sev-critical hover:opacity-100"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </span>
          );
        })}

        {/* Saving is only meaningful once there is a filter to save, and
            offering it twice for the same filter just creates duplicates. */}
        {trimmed && !already && !naming ? (
          <button className="btn py-1 text-xs" onClick={() => setNaming(true)}>
            <Plus className="h-3 w-3" />
            Save this filter
          </button>
        ) : null}

        {trimmed && already ? (
          <span className="inline-flex items-center gap-1 text-xs text-slate-600">
            <Check className="h-3 w-3" />
            Already saved
          </span>
        ) : null}
      </div>

      {naming ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <input
            className="input max-w-xs text-xs"
            placeholder="Name this view"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            autoFocus
          />
          <button type="submit" className="btn-primary py-1 text-xs" disabled={action.busy || !name.trim()}>
            {action.busy ? "Saving" : "Save"}
          </button>
          <button
            type="button"
            className="btn py-1 text-xs"
            onClick={() => {
              setNaming(false);
              action.reset();
            }}
          >
            <X className="h-3 w-3" />
            Cancel
          </button>
          <span className="font-mono text-[11px] text-slate-600">{trimmed}</span>
        </form>
      ) : null}

      {action.parked ? (
        <ApprovalBanner approval={action.parked} message={action.message} onDismiss={action.reset} />
      ) : null}
      {action.error ? <p className="text-xs text-sev-critical">{action.error}</p> : null}
    </div>
  );
}
