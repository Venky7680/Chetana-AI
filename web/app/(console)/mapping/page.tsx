"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { MappingSuggestions } from "@/components/MappingSuggestions";
import { EmptyState, ErrorState, GatedAction, ProblemBanner, Spinner } from "@/components/ui";

interface Rule {
  id: string;
  name: string;
  description?: string;
  disabled?: boolean;
  matchers?: string[];
  attributes?: string[];
  type?: string;
  priority?: number;
  created_by?: string;
}

const EXAMPLE_ROWS = `[
  { "service": "payments-api", "owning_team": "Payments Engineering", "support_tier": "gold" },
  { "service": "ledger-worker", "owning_team": "Core Banking", "support_tier": "gold" }
]`;

export default function MappingPage() {
  const { can } = useSession();
  const { data, error, loading, reload } = useApi<{ mapping: Rule[]; problems?: string[] }>("/enrichment");
  const action = useAction();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    matchers: "service",
    priority: 0,
    rows: EXAMPLE_ROWS,
  });
  const [rowsError, setRowsError] = useState<string | null>(null);

  const rules = Array.isArray(data?.mapping) ? data.mapping : [];

  async function create() {
    let rows: unknown;
    try {
      rows = JSON.parse(form.rows);
    } catch {
      setRowsError("The lookup table must be valid JSON — an array of objects.");
      return;
    }
    if (!Array.isArray(rows) || rows.length === 0) {
      setRowsError("Provide at least one row, as a JSON array of objects.");
      return;
    }
    setRowsError(null);

    const result = await action.run("/mapping", {
      body: {
        name: form.name,
        description: form.description || null,
        type: "csv",
        priority: Number(form.priority),
        // Outer list is OR, inner is AND — Keep rejects a flat list.
        matchers: form.matchers
          .split(",")
          .map((group) => group.split("+").map((f) => f.trim()).filter(Boolean))
          .filter((group) => group.length > 0),
        rows,
      },
      successMessage: "Mapping rule created in Keep",
    });
    if (result !== null) setShowForm(false);
    reload();
  }

  async function remove(id: string) {
    await action.run(`/mapping/${id}`, { method: "DELETE", successMessage: "Rule deleted" });
    reload();
  }

  if (loading && !data) return <Spinner label="Reading mapping rules" />;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
        <h1 className="text-xl font-semibold text-slate-100">Mapping</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Decorates an incoming alert with fields it did not carry — owning team, support tier, CMDB
          id, business criticality — by matching on something it did. This is what turns a bare
          hostname into something a NOC can route.
        </p>
        </div>
        <GatedAction
          capability={can("mapping.create")}
          busy={action.busy}
          onClick={() => setShowForm((v) => !v)}
        >
          <Plus className="h-3.5 w-3.5" />
          New mapping rule
        </GatedAction>
      </header>

      <ProblemBanner problems={data?.problems} />
      <MappingSuggestions onCreated={reload} />
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
          <h2 className="text-sm font-semibold text-slate-200">New mapping rule</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block">
              <span className="label mb-1.5 block">Name</span>
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Service ownership"
              />
            </label>
            <label className="block">
              <span className="label mb-1.5 block">Match on</span>
              <input
                className="input font-mono text-xs"
                value={form.matchers}
                onChange={(e) => setForm({ ...form, matchers: e.target.value })}
                placeholder="service"
              />
            </label>
            <label className="block">
              <span className="label mb-1.5 block">Priority</span>
              <input
                className="input"
                type="number"
                min={0}
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}
              />
            </label>
          </div>
          <p className="text-xs text-slate-600">
            Comma separates alternatives, <span className="font-mono">+</span> combines fields that
            must all match — so <span className="font-mono">service, environment+team</span> means
            &quot;match on service, or on environment and team together&quot;.
          </p>
          <label className="block">
            <span className="label mb-1.5 block">Description</span>
            <input
              className="input"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Adds owning team and support tier"
            />
          </label>
          <label className="block">
            <span className="label mb-1.5 block">Lookup table (JSON rows)</span>
            <textarea
              spellCheck={false}
              className="input h-40 resize-y font-mono text-xs"
              value={form.rows}
              onChange={(e) => {
                setForm({ ...form, rows: e.target.value });
                if (rowsError) setRowsError(null);
              }}
            />
          </label>
          {rowsError ? (
            <p className="rounded-lg border border-sev-critical/30 bg-sev-critical/5 px-3 py-2 text-xs text-sev-critical">
              {rowsError}
            </p>
          ) : null}
          <div className="flex items-center gap-2">
            <GatedAction capability={can("mapping.create")} busy={action.busy} onClick={create}>
              Create rule
            </GatedAction>
            <button className="btn" onClick={() => setShowForm(false)}>
              Cancel
            </button>
          </div>
        </section>
      ) : null}

      <section className="card overflow-hidden">
        {rules.length === 0 ? (
          <EmptyState
            title="No mapping rules"
            hint="Use New mapping rule above — a name, what to match on, and a small lookup table."
          />
        ) : (
          <table className="w-full">
            <thead className="bg-surface-overlay/40">
              <tr>
                <th className="th">Rule</th>
                <th className="th">Matches on</th>
                <th className="th">Adds</th>
                <th className="th">Priority</th>
                <th className="th">State</th>
                <th className="th" />
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id} className="row">
                  <td className="td">
                    <p className="font-medium text-slate-200">{rule.name}</p>
                    {rule.description ? (
                      <p className="mt-0.5 text-xs text-slate-600">{rule.description}</p>
                    ) : null}
                    {rule.created_by ? (
                      <p className="mt-0.5 text-xs text-slate-600">{rule.created_by}</p>
                    ) : null}
                  </td>
                  <td className="td">
                    <div className="flex flex-wrap gap-1">
                      {(rule.matchers ?? []).map((m) => (
                        <span key={m} className="chip font-mono">
                          {m}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="td">
                    <div className="flex flex-wrap gap-1">
                      {(rule.attributes ?? []).length === 0 ? (
                        <span className="text-slate-600">—</span>
                      ) : (
                        (rule.attributes ?? []).map((a) => (
                          <span key={a} className="chip font-mono">
                            {a}
                          </span>
                        ))
                      )}
                    </div>
                  </td>
                  <td className="td tabular-nums">{rule.priority ?? "—"}</td>
                  <td className="td">
                    <span className={rule.disabled ? "text-slate-600" : "text-emerald-400"}>
                      {rule.disabled ? "disabled" : "active"}
                    </span>
                  </td>
                  <td className="td">
                    <GatedAction
                      capability={can("mapping.delete")}
                      busy={action.busy}
                      variant="danger"
                      onClick={() => remove(rule.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </GatedAction>
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
