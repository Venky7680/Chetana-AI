"use client";

import { useState } from "react";
import { AlertTriangle, Sparkles, X } from "lucide-react";
import { useApi } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { EmptyState, ErrorState, Spinner } from "@/components/ui";

/**
 * Routing rules proposed from ticket history.
 *
 * These are derived offline from an ITSM export: every CI class in the data,
 * and the team that actually picked its tickets up. Turning that into a mapping
 * rule is the difference between an alert arriving as a bare hostname and
 * arriving with an owner attached.
 *
 * The split between "ready" and "needs review" is the whole value of the panel.
 * A CI class whose tickets nearly always went to one team is a rule. One that
 * splits between two teams routes by *symptom*, not by component, so a rule
 * there would mis-route about half of them — silently, and always towards
 * whichever team happened to be more common in the export. Those are shown but
 * never included, because a wrong owner is worse than no owner: it looks
 * handled.
 */

interface ReadyRow {
  ci_class: string;
  owning_team: string;
  support_tier: string;
}

interface AmbiguousRow extends ReadyRow {
  confidence: number;
  also: string[];
}

export function MappingSuggestions({ onCreated }: { onCreated: () => void }) {
  const { data, error, loading } = useApi<{
    ready: ReadyRow[];
    needs_review: AmbiguousRow[];
  }>("/mapping/suggestions");
  const action = useAction();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("Service ownership from ticket history");

  const ready = data?.ready ?? [];
  const review = data?.needs_review ?? [];

  async function create() {
    if (ready.length === 0) return;
    const done = await action.run("/mapping", {
      body: {
        name: name.trim() || "Service ownership from ticket history",
        description: `Derived from ticket history — ${ready.length} CI classes with a clear owner.`,
        type: "csv",
        priority: 10,
        matchers: [["service"]],
        rows: ready.map((row) => ({
          service: row.ci_class,
          owning_team: row.owning_team,
          support_tier: row.support_tier,
        })),
      },
      successMessage: "Mapping rule created",
    });
    if (!done) return;
    setOpen(false);
    onCreated();
  }

  // Nothing generated for this deployment — say nothing rather than show an
  // empty panel that looks broken.
  if (!loading && !error && ready.length === 0 && review.length === 0) return null;

  return (
    <div className="space-y-3">
      <button className={open ? "btn-primary" : "btn"} onClick={() => setOpen((v) => !v)}>
        <Sparkles className="h-3.5 w-3.5" />
        Suggest rules from ticket history
      </button>

      {open ? (
        <section className="card-pad space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-200">
                Proposed service ownership
              </h3>
              <p className="mt-0.5 max-w-2xl text-xs text-slate-600">
                Every CI class in the ticket export, matched to the team that actually resolved
                its tickets. Creating this rule means an alert carrying a matching{" "}
                <code className="font-mono">service</code> arrives with an owner and a support
                tier already on it.
              </p>
            </div>
            <button onClick={() => setOpen(false)} aria-label="Close" className="text-slate-600 hover:text-slate-300">
              <X className="h-4 w-4" />
            </button>
          </div>

          {loading ? <Spinner label="Reading suggestions" /> : null}
          {error ? <ErrorState message={error} /> : null}

          {ready.length > 0 ? (
            <>
              <div className="max-h-72 overflow-y-auto rounded-lg border border-surface-border">
                <table className="w-full">
                  <thead className="sticky top-0 bg-surface-overlay">
                    <tr>
                      <th className="th">CI class</th>
                      <th className="th">Owning team</th>
                      <th className="th">Support tier</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ready.map((row) => (
                      <tr key={row.ci_class} className="row">
                        <td className="td font-mono text-xs text-slate-200">{row.ci_class}</td>
                        <td className="td">{row.owning_team}</td>
                        <td className="td capitalize text-slate-400">{row.support_tier}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <label className="block max-w-md">
                <span className="label">Rule name</span>
                <input
                  className="input mt-1"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={120}
                />
              </label>

              <div className="flex items-center gap-2">
                <button className="btn-primary" onClick={create} disabled={action.busy}>
                  {action.busy ? "Creating" : `Create rule with ${ready.length} rows`}
                </button>
                <span className="text-xs text-slate-600">Matches on service, priority 10.</span>
              </div>
            </>
          ) : null}

          {review.length > 0 ? (
            <div className="rounded-lg border border-sev-warning/30 bg-sev-warning/5 px-4 py-3">
              <h4 className="flex items-center gap-2 text-xs font-semibold text-sev-warning">
                <AlertTriangle className="h-3.5 w-3.5" />
                {review.length} left out — these route by symptom, not by component
              </h4>
              <p className="mt-1 text-xs text-slate-500">
                Each of these splits between teams in the history, so a single rule would send
                roughly half of them to the wrong place. A wrong owner is worse than no owner:
                it looks handled. Add them by hand, or match on something narrower than the CI
                class.
              </p>
              <ul className="mt-2.5 space-y-1">
                {review.map((row) => (
                  <li key={row.ci_class} className="flex flex-wrap items-baseline gap-x-2 text-xs">
                    <span className="font-mono text-slate-300">{row.ci_class}</span>
                    <span className="text-slate-500">
                      {Math.round(row.confidence * 100)}% {row.owning_team}
                    </span>
                    {row.also.length > 0 ? (
                      <span className="text-slate-600">· also {row.also.join(", ")}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {action.parked ? (
            <ApprovalBanner approval={action.parked} message={action.message} onDismiss={action.reset} />
          ) : null}
          {action.error ? <ErrorState message={action.error} /> : null}
          {ready.length === 0 && !loading ? (
            <EmptyState title="Nothing confident enough to propose" />
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
