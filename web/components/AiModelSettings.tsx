"use client";

import { useState } from "react";
import { Bot, RotateCcw } from "lucide-react";
import { useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { ErrorState, GatedAction } from "@/components/ui";

/**
 * Tune one of Keep's AI correlation models without leaving Chetana.
 *
 * Keep types this config's `settings` as an untyped list, and its shape differs
 * per model and per Keep version. Rather than assume a schema that would break
 * on the next release, each setting is rendered from what it actually looks
 * like — a boolean becomes a switch, a bounded number becomes a slider — and
 * anything unrecognised falls through to the JSON editor. A shape we cannot
 * read should not become a page nobody can use.
 *
 * Keep replaces the whole config object rather than patching it, so the object
 * read from the server is sent back with only `settings` changed.
 */

export interface AiConfig {
  id: string;
  algorithm_id: string;
  tenant_id: string;
  settings: unknown[];
  settings_proposed_by_algorithm?: unknown[] | null;
  feedback_logs?: string | null;
  algorithm?: { name?: string; description?: string };
}

type Setting = Record<string, unknown>;

function isSetting(value: unknown): value is Setting {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function label(setting: Setting, index: number): string {
  for (const key of ["name", "key", "title", "id"]) {
    const value = setting[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return `Setting ${index + 1}`;
}

export function AiModelSettings({
  config,
  onSaved,
}: {
  config: AiConfig;
  onSaved: () => void;
}) {
  const { can } = useSession();
  const action = useAction();

  const initial = Array.isArray(config.settings) ? config.settings : [];
  const [settings, setSettings] = useState<unknown[]>(initial);
  const [rawMode, setRawMode] = useState(false);
  const [raw, setRaw] = useState(() => JSON.stringify(initial, null, 2));
  const [problem, setProblem] = useState<string | null>(null);

  const dirty = JSON.stringify(settings) !== JSON.stringify(initial);
  const name = config.algorithm?.name ?? config.algorithm_id;

  function update(index: number, patch: Setting) {
    setSettings(settings.map((s, i) => (i === index && isSetting(s) ? { ...s, ...patch } : s)));
  }

  function reset() {
    setSettings(initial);
    setRaw(JSON.stringify(initial, null, 2));
    setProblem(null);
    action.reset();
  }

  async function save() {
    let next = settings;
    if (rawMode) {
      try {
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) {
          setProblem("Settings must be a JSON array.");
          return;
        }
        next = parsed;
      } catch {
        setProblem("That is not valid JSON.");
        return;
      }
    }
    setProblem(null);

    // Keep wants the whole object back, not a patch.
    const result = await action.run(`/ai/${encodeURIComponent(config.algorithm_id)}/settings`, {
      method: "PUT",
      body: { config: { ...config, settings: next }, reason: `Tuned ${name} from the console` },
      successMessage: `${name} updated`,
    });
    if (result !== null) {
      setSettings(next);
      onSaved();
    }
  }

  return (
    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-border px-5 py-3.5">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Bot className="h-4 w-4 text-accent" />
            {name}
          </h2>
          {config.algorithm?.description ? (
            <p className="mt-0.5 max-w-2xl text-xs text-slate-600">
              {config.algorithm.description}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {dirty ? (
            <button className="btn" onClick={reset} title="Discard changes">
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          ) : null}
          <GatedAction
            capability={can("ai.settings")}
            busy={action.busy}
            onClick={save}
          >
            Apply
          </GatedAction>
        </div>
      </div>

      {action.parked ? (
        <div className="px-5 pt-4">
          <ApprovalBanner
            approval={action.parked}
            message={action.message}
            onDismiss={action.reset}
          />
        </div>
      ) : null}
      {action.error ? (
        <div className="px-5 pt-4">
          <ErrorState message={action.error} />
        </div>
      ) : null}
      {action.message && !action.parked ? (
        <p className="mx-5 mt-4 rounded-lg border border-emerald-700/40 bg-emerald-500/5 px-3 py-2 text-sm text-emerald-400">
          {action.message}
        </p>
      ) : null}

      <div className="space-y-4 px-5 py-4">
        {rawMode || settings.length === 0 || !settings.every(isSetting) ? (
          <label className="block">
            <span className="label mb-1.5 block">Settings (JSON)</span>
            <textarea
              spellCheck={false}
              className="input h-48 resize-y font-mono text-xs"
              value={raw}
              onChange={(e) => {
                setRaw(e.target.value);
                if (problem) setProblem(null);
              }}
            />
            <span className="mt-1 block text-xs text-slate-600">
              {settings.length === 0
                ? "This model reports no settings yet."
                : "This model's settings do not match a shape the form can render, so they are edited directly."}
            </span>
          </label>
        ) : (
          <div className="space-y-3">
            {settings.map((setting, index) => {
              if (!isSetting(setting)) return null;
              const value = setting.value;
              const min = typeof setting.min === "number" ? setting.min : undefined;
              const max = typeof setting.max === "number" ? setting.max : undefined;

              return (
                <div key={index} className="rounded-lg border border-surface-border px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm text-slate-200">{label(setting, index)}</p>
                      {typeof setting.description === "string" ? (
                        <p className="mt-0.5 max-w-xl text-xs text-slate-600">
                          {setting.description}
                        </p>
                      ) : null}
                    </div>

                    {typeof value === "boolean" ? (
                      <label className="flex shrink-0 items-center gap-2 text-sm text-slate-300">
                        <input
                          type="checkbox"
                          checked={value}
                          onChange={(e) => update(index, { value: e.target.checked })}
                          className="h-3.5 w-3.5 rounded border-surface-border bg-surface-base accent-accent"
                        />
                        {value ? "enabled" : "disabled"}
                      </label>
                    ) : typeof value === "number" ? (
                      <div className="flex shrink-0 items-center gap-2">
                        {min !== undefined && max !== undefined ? (
                          <input
                            type="range"
                            min={min}
                            max={max}
                            step={Number.isInteger(min) && Number.isInteger(max) ? 1 : 0.01}
                            value={value}
                            onChange={(e) => update(index, { value: Number(e.target.value) })}
                            className="w-40 accent-accent"
                          />
                        ) : null}
                        <input
                          type="number"
                          className="input w-24 tabular-nums"
                          min={min}
                          max={max}
                          value={value}
                          onChange={(e) => update(index, { value: Number(e.target.value) })}
                        />
                      </div>
                    ) : (
                      <input
                        className="input w-56 font-mono text-xs"
                        value={typeof value === "string" ? value : JSON.stringify(value ?? "")}
                        onChange={(e) => update(index, { value: e.target.value })}
                      />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {problem ? (
          <p className="rounded-lg border border-sev-critical/30 bg-sev-critical/5 px-3 py-2 text-xs text-sev-critical">
            {problem}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          {settings.length > 0 && settings.every(isSetting) ? (
            <button
              className="text-xs text-slate-500 underline hover:text-slate-300"
              onClick={() => {
                setRaw(JSON.stringify(settings, null, 2));
                setRawMode((v) => !v);
              }}
            >
              {rawMode ? "use the form" : "edit as JSON"}
            </button>
          ) : null}
          <span className="text-xs text-slate-600">
            Changing how a model correlates is tier R2 — it alters what the platform does
            unattended, so it goes through approval.
          </span>
        </div>
      </div>
    </section>
  );
}
