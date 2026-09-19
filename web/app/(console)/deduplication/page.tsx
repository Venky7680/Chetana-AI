"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import type { DedupRule } from "@/lib/types";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import {
  EmptyState,
  ErrorState,
  GatedAction,
  ProblemBanner,
  Spinner,
  StatCard,
} from "@/components/ui";

export default function DeduplicationPage() {
  const { data, error, loading, reload } = useApi<{
    rules: DedupRule[];
    fields: Record<string, string[]>;
    problems?: string[];
  }>("/deduplications");

  const { can } = useSession();
  const action = useAction();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    provider_type: "prometheus",
    fingerprint_fields: "labels.alertname, labels.instance",
    full_deduplication: false,
  });

  const rules = Array.isArray(data?.rules) ? data.rules : [];
  const providerTypes = Array.from(
    new Set(rules.map((r) => r.provider_type).filter((p): p is string => Boolean(p))),
  );

  async function create() {
    const result = await action.run("/deduplications", {
      body: {
        name: form.name,
        description: form.description || null,
        provider_type: form.provider_type,
        fingerprint_fields: form.fingerprint_fields
          .split(",")
          .map((f) => f.trim())
          .filter(Boolean),
        full_deduplication: form.full_deduplication,
      },
      successMessage: "Deduplication rule created in Keep",
    });
    if (result !== null) setShowForm(false);
    reload();
  }

  async function remove(id: string) {
    await action.run(`/deduplications/${id}`, { method: "DELETE", successMessage: "Rule deleted" });
    reload();
  }

  if (loading && !data) return <Spinner label="Reading deduplication rules" />;
  const ingested = rules.reduce((n, r) => n + (r.ingested ?? 0), 0);
  const weighted = rules.reduce((n, r) => n + (r.dedup_ratio ?? 0) * (r.ingested ?? 0), 0);
  const overall = ingested > 0 ? weighted / ingested : 0;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
        <h1 className="text-xl font-semibold text-slate-100">Deduplication</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          The first noise-reduction layer: identical alerts arriving repeatedly collapse into one,
          keyed on the fingerprint fields below. This happens before correlation, so a flapping
          check never becomes a hundred incidents.
        </p>
        </div>
        <GatedAction
          capability={can("dedup.create")}
          busy={action.busy}
          onClick={() => setShowForm((v) => !v)}
        >
          <Plus className="h-3.5 w-3.5" />
          New rule
        </GatedAction>
      </header>

      <ProblemBanner problems={data?.problems} />
      {error ? <ErrorState message={error} onRetry={reload} /> : null}
      {action.parked ? (
        <ApprovalBanner approval={action.parked} message={action.message} onDismiss={action.reset} />
      ) : null}
      {action.error ? <ErrorState message={action.error} /> : null}
      {action.message && !action.parked ? (
        <p className="rounded-lg border border-emerald-700/40 bg-emerald-500/5 px-3 py-2 text-sm text-emerald-400">
          {action.message}
        </p>
      ) : null}

      {showForm ? (
        <section className="card-pad space-y-3">
          <h2 className="text-sm font-semibold text-slate-200">New deduplication rule</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="label mb-1.5 block">Name</span>
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Prometheus by alertname and instance"
              />
            </label>
            <label className="block">
              <span className="label mb-1.5 block">Provider type</span>
              <input
                className="input font-mono text-xs"
                list="dedup-provider-types"
                value={form.provider_type}
                onChange={(e) => setForm({ ...form, provider_type: e.target.value })}
              />
              <datalist id="dedup-provider-types">
                {providerTypes.map((p) => (
                  <option key={p} value={p} />
                ))}
              </datalist>
            </label>
          </div>
          <label className="block">
            <span className="label mb-1.5 block">Fingerprint fields</span>
            <input
              className="input font-mono text-xs"
              value={form.fingerprint_fields}
              onChange={(e) => setForm({ ...form, fingerprint_fields: e.target.value })}
              placeholder="labels.alertname, labels.instance"
            />
          </label>
          <p className="text-xs text-slate-600">
            Two alerts whose values match on every one of these fields are treated as the same
            alert. Fewer fields collapse more aggressively; more fields keep things apart.
          </p>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={form.full_deduplication}
              onChange={(e) => setForm({ ...form, full_deduplication: e.target.checked })}
              className="h-3.5 w-3.5 rounded border-surface-border bg-surface-base accent-accent"
            />
            Full deduplication — compare the entire payload, not just these fields
          </label>
          <div className="flex items-center gap-2">
            <GatedAction capability={can("dedup.create")} busy={action.busy} onClick={create}>
              Create rule
            </GatedAction>
            <button className="btn" onClick={() => setShowForm(false)}>
              Cancel
            </button>
          </div>
        </section>
      ) : null}

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        <StatCard label="Rules" value={rules.length} />
        <StatCard label="Alerts ingested" value={ingested.toLocaleString()} />
        <StatCard
          label="Collapsed by dedup"
          value={`${overall.toFixed(1)}%`}
          hint="Weighted by volume across every rule"
          tone={overall > 0 ? "good" : "default"}
        />
      </section>

      <section className="card overflow-hidden">
        <div className="border-b border-surface-border px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-200">Rules</h2>
        </div>
        {rules.length === 0 ? (
          <EmptyState
            title="No deduplication rules yet"
            hint="Keep creates a default rule per provider the first time that provider sends an alert."
          />
        ) : (
          <table className="w-full">
            <thead className="bg-surface-overlay/40">
              <tr>
                <th className="th">Rule</th>
                <th className="th">Provider</th>
                <th className="th">Fingerprint fields</th>
                <th className="th">Ingested</th>
                <th className="th">Deduped</th>
                <th className="th" />
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id} className="row">
                  <td className="td">
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-slate-200">{rule.name}</p>
                      {rule.default ? <span className="chip">default</span> : null}
                      {rule.full_deduplication ? <span className="chip">full</span> : null}
                    </div>
                    {rule.description ? (
                      <p className="mt-0.5 text-xs text-slate-600">{rule.description}</p>
                    ) : null}
                  </td>
                  <td className="td text-slate-400">{rule.provider_type ?? "—"}</td>
                  <td className="td">
                    <div className="flex flex-wrap gap-1">
                      {(rule.fingerprint_fields ?? []).map((field) => (
                        <span key={field} className="chip font-mono">
                          {field}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="td tabular-nums">{(rule.ingested ?? 0).toLocaleString()}</td>
                  <td className="td tabular-nums">
                    {rule.dedup_ratio !== undefined ? (
                      <span className="text-emerald-400">
                        {Number(rule.dedup_ratio).toFixed(1)}%
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="td">
                    {rule.default ? (
                      <span className="text-xs text-slate-600">built in</span>
                    ) : (
                      <GatedAction
                        capability={can("dedup.delete")}
                        busy={action.busy}
                        variant="danger"
                        onClick={() => remove(rule.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </GatedAction>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <div className="border-b border-surface-border px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-200">Fields available per provider</h2>
          <p className="mt-0.5 text-xs text-slate-600">
            What a fingerprint can be built from, per source.
          </p>
        </div>
        {Object.keys(data?.fields ?? {}).length === 0 ? (
          <EmptyState title="No field map reported" />
        ) : (
          <div className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(data?.fields ?? {}).map(([provider, fields]) => (
              <div key={provider} className="rounded-lg border border-surface-border px-4 py-3">
                <p className="text-sm text-slate-200">{provider}</p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {(Array.isArray(fields) ? fields : []).slice(0, 10).map((field) => (
                    <span key={String(field)} className="chip font-mono">
                      {String(field)}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
