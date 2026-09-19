"use client";

import { useState } from "react";
import { GitMerge, Plus } from "lucide-react";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import type { CorrelationRule } from "@/lib/types";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { EmptyState, ErrorState, GatedAction, Spinner } from "@/components/ui";

export default function CorrelationPage() {
  const { can } = useSession();
  const rules = useApi<CorrelationRule[]>("/rules");
  const action = useAction();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", cel: "", timeframe_seconds: 900, grouping: "service" });

  async function create() {
    await action.run("/rules", {
      body: {
        name: form.name,
        cel: form.cel,
        timeframe_seconds: Number(form.timeframe_seconds),
        grouping: form.grouping
          .split(",")
          .map((g) => g.trim())
          .filter(Boolean),
      },
      successMessage: "Correlation rule created",
    });
    rules.reload();
  }

  const ruleList = Array.isArray(rules.data) ? rules.data : [];

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Correlations</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Deduplication collapses repeats of the <em>same</em> alert. Correlation is the layer
            above it: grouping <em>different</em> alerts that belong to one problem into a single
            incident, so a failing dependency reads as one thing rather than six.
          </p>
        </div>
        <GatedAction
          capability={can("rules.create")}
          busy={action.busy}
          onClick={() => setShowForm((v) => !v)}
        >
          <Plus className="h-3.5 w-3.5" />
          New rule
        </GatedAction>
      </header>

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
          <h2 className="text-sm font-semibold text-slate-200">New correlation rule</h2>
          <p className="text-xs text-slate-500">
            A CEL predicate plus a window. Alerts matching the predicate within the window are
            grouped into one incident. Changing grouping affects every future alert for this
            client, which is why it is tier R2.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="label mb-1.5 block">Name</span>
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Payments path degradation"
              />
            </label>
            <label className="block">
              <span className="label mb-1.5 block">Window (seconds)</span>
              <input
                className="input"
                type="number"
                min={60}
                value={form.timeframe_seconds}
                onChange={(e) => setForm({ ...form, timeframe_seconds: Number(e.target.value) })}
              />
            </label>
          </div>
          <label className="block">
            <span className="label mb-1.5 block">CEL predicate</span>
            <input
              className="input font-mono text-xs"
              value={form.cel}
              onChange={(e) => setForm({ ...form, cel: e.target.value })}
              placeholder='service == "payments-api" || service == "ledger-worker"'
            />
          </label>
          <label className="block">
            <span className="label mb-1.5 block">Group by (comma separated)</span>
            <input
              className="input font-mono text-xs"
              value={form.grouping}
              onChange={(e) => setForm({ ...form, grouping: e.target.value })}
            />
          </label>
          <div className="flex gap-2">
            <GatedAction capability={can("rules.create")} busy={action.busy} onClick={create}>
              Create rule
            </GatedAction>
            <button className="btn" onClick={() => setShowForm(false)}>
              Cancel
            </button>
          </div>
        </section>
      ) : null}

      <section className="card">
        <div className="flex items-center gap-2 border-b border-surface-border px-5 py-3.5">
          <GitMerge className="h-4 w-4 text-slate-500" />
          <h2 className="text-sm font-semibold text-slate-200">
            Correlation rules <span className="text-slate-600">({ruleList.length})</span>
          </h2>
        </div>
        {rules.error ? (
          <div className="p-5">
            <ErrorState message={rules.error} onRetry={rules.reload} />
          </div>
        ) : rules.loading && !rules.data ? (
          <Spinner />
        ) : ruleList.length === 0 ? (
          <EmptyState
            title="No correlation rules"
            hint="Keep still groups by its built-in heuristics; a rule makes the grouping explicit."
          />
        ) : (
          <table className="w-full">
            <thead className="bg-surface-overlay/40">
              <tr>
                <th className="th">Rule</th>
                <th className="th">Predicate</th>
                <th className="th">Window</th>
                <th className="th">Group by</th>
              </tr>
            </thead>
            <tbody>
              {ruleList.map((rule) => (
                <tr key={rule.id} className="row">
                  <td className="td">
                    <p className="font-medium text-slate-200">{rule.name}</p>
                    {rule.created_by ? (
                      <p className="mt-0.5 text-xs text-slate-600">{rule.created_by}</p>
                    ) : null}
                  </td>
                  <td className="td max-w-md break-all font-mono text-xs text-slate-400">
                    {rule.definition_cel ?? "—"}
                  </td>
                  <td className="td whitespace-nowrap">
                    {rule.timeframe ? `${Math.round(rule.timeframe / 60)} min` : "—"}
                  </td>
                  <td className="td">
                    <div className="flex flex-wrap gap-1">
                      {(rule.grouping_criteria ?? []).map((g) => (
                        <span key={g} className="chip font-mono">
                          {g}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

    </div>
  );
}
