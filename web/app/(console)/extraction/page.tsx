"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { EmptyState, ErrorState, GatedAction, ProblemBanner, Spinner } from "@/components/ui";

interface Rule {
  id: string;
  name: string;
  description?: string;
  disabled?: boolean;
  attribute?: string;
  regex?: string;
  condition?: string;
  pre?: boolean;
  priority?: number;
}

export default function ExtractionPage() {
  const { can } = useSession();
  const { data, error, loading, reload } = useApi<{ extraction: Rule[]; problems?: string[] }>("/enrichment");
  const action = useAction();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    attribute: "description",
    regex: String.raw`instance=(?P<instance>[\w\.\-:]+)`,
    priority: 0,
    pre: true,
  });
  const [regexError, setRegexError] = useState<string | null>(null);

  const rules = Array.isArray(data?.extraction) ? data.extraction : [];

  async function create() {
    // Python's named groups are (?P<name>...); JavaScript uses (?<name>...).
    // Validate the JS equivalent so an obvious mistake is caught here rather
    // than silently extracting nothing in Keep forever.
    try {
      new RegExp(form.regex.replace(/\(\?P</g, "(?<"));
    } catch (err) {
      setRegexError(err instanceof Error ? err.message : "That is not a valid regular expression.");
      return;
    }
    if (!/\(\?P?</.test(form.regex)) {
      setRegexError(
        "The pattern needs at least one named capture group, like (?P<instance>...) — that name becomes the new field.",
      );
      return;
    }
    setRegexError(null);

    const result = await action.run("/extraction", {
      body: {
        name: form.name,
        description: form.description || null,
        attribute: form.attribute,
        regex: form.regex,
        priority: Number(form.priority),
        pre: form.pre,
        disabled: false,
      },
      successMessage: "Extraction rule created in Keep",
    });
    if (result !== null) setShowForm(false);
    reload();
  }

  async function remove(id: string) {
    await action.run(`/extraction/${id}`, { method: "DELETE", successMessage: "Rule deleted" });
    reload();
  }

  if (loading && !data) return <Spinner label="Reading extraction rules" />;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
        <h1 className="text-xl font-semibold text-slate-100">Extraction</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Pulls structure out of free text. Monitoring tools bury the useful part — the instance,
          the cluster, the queue name — inside a description string. A named capture group promotes
          it to a real field, which then becomes filterable, groupable and correlatable.
        </p>
        </div>
        <GatedAction
          capability={can("extraction.create")}
          busy={action.busy}
          onClick={() => setShowForm((v) => !v)}
        >
          <Plus className="h-3.5 w-3.5" />
          New extraction rule
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
          <h2 className="text-sm font-semibold text-slate-200">New extraction rule</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block">
              <span className="label mb-1.5 block">Name</span>
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Instance from description"
              />
            </label>
            <label className="block">
              <span className="label mb-1.5 block">Read from field</span>
              <input
                className="input font-mono text-xs"
                value={form.attribute}
                onChange={(e) => setForm({ ...form, attribute: e.target.value })}
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
          <label className="block">
            <span className="label mb-1.5 block">Pattern</span>
            <input
              spellCheck={false}
              className="input font-mono text-xs"
              value={form.regex}
              onChange={(e) => {
                setForm({ ...form, regex: e.target.value });
                if (regexError) setRegexError(null);
              }}
            />
          </label>
          <p className="text-xs text-slate-600">
            Each named group becomes a new field on the alert. Keep uses Python syntax:{" "}
            <span className="font-mono">(?P&lt;name&gt;...)</span>.
          </p>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={form.pre}
              onChange={(e) => setForm({ ...form, pre: e.target.checked })}
              className="h-3.5 w-3.5 rounded border-surface-border bg-surface-base accent-accent"
            />
            Run before enrichment, so Mapping rules can match on what this extracts
          </label>
          {regexError ? (
            <p className="rounded-lg border border-sev-critical/30 bg-sev-critical/5 px-3 py-2 text-xs text-sev-critical">
              {regexError}
            </p>
          ) : null}
          <div className="flex items-center gap-2">
            <GatedAction capability={can("extraction.create")} busy={action.busy} onClick={create}>
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
            title="No extraction rules"
            hint="Use New extraction rule above — pick a field, write a pattern with a named group."
          />
        ) : (
          <table className="w-full">
            <thead className="bg-surface-overlay/40">
              <tr>
                <th className="th">Rule</th>
                <th className="th">Reads</th>
                <th className="th">Pattern</th>
                <th className="th">When</th>
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
                  </td>
                  <td className="td">
                    {rule.attribute ? (
                      <span className="chip font-mono">{rule.attribute}</span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="td max-w-sm break-all font-mono text-xs text-slate-400">
                    {rule.regex ?? "—"}
                  </td>
                  <td className="td text-xs text-slate-500">
                    {rule.pre ? "before enrichment" : "after enrichment"}
                    {rule.condition ? (
                      <span className="mt-0.5 block break-all font-mono text-slate-600">
                        {rule.condition}
                      </span>
                    ) : null}
                  </td>
                  <td className="td">
                    <span className={rule.disabled ? "text-slate-600" : "text-emerald-400"}>
                      {rule.disabled ? "disabled" : "active"}
                    </span>
                  </td>
                  <td className="td">
                    <GatedAction
                      capability={can("extraction.delete")}
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
