"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { GitMerge, Plus, Trash2 } from "lucide-react";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import type { Envelope, Incident } from "@/lib/types";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { applyFacets, FacetSidebar, type Facet, type FacetSelection } from "@/components/Facets";
import {
  EmptyState,
  ErrorState,
  GatedAction,
  RelativeTime,
  SeverityBadge,
  Spinner,
  StatusDot,
} from "@/components/ui";

const RANGES = [
  { label: "All time", hours: 0 },
  { label: "Last hour", hours: 1 },
  { label: "Last 24 hours", hours: 24 },
  { label: "Last 7 days", hours: 24 * 7 },
];

type Faceted = Envelope<Incident> & { facets: Facet[] };

export default function IncidentsPage() {
  const { can } = useSession();
  const [selection, setSelection] = useState<FacetSelection>({});
  const [checked, setChecked] = useState<string[]>([]);
  const [range, setRange] = useState(0);
  const [showCreate, setShowCreate] = useState(false);
  const [draft, setDraft] = useState({ name: "", summary: "" });
  const action = useAction();

  const { data, error, loading, reload } = useApi<Faceted>("/incidents", {
    query: { limit: 200 },
  });

  const rows = useMemo(() => {
    let items = data?.items ?? [];
    if (range > 0) {
      const cutoff = Date.now() - range * 3600_000;
      items = items.filter((i) => {
        const at = i.last_seen_at ?? i.created_at;
        return at ? new Date(at).getTime() >= cutoff : true;
      });
    }
    return applyFacets(items, selection, (incident, key) => {
      switch (key) {
        case "status":
          return incident.status;
        case "severity":
          return incident.severity;
        case "assignee":
          return incident.assignee ?? "None";
        case "source":
          return incident.sources.length ? incident.sources : "None";
        case "service":
          return incident.services.length ? incident.services : "None";
        case "linked":
          return incident.rule_id ? "Yes" : "No";
        default:
          return "None";
      }
    });
  }, [data, selection, range]);

  const allChecked = rows.length > 0 && checked.length === rows.length;

  async function createIncident() {
    await action.run("/incidents", {
      body: { user_generated_name: draft.name, user_summary: draft.summary, status: "firing" },
      successMessage: "Incident created",
    });
    setDraft({ name: "", summary: "" });
    setShowCreate(false);
    reload();
  }

  async function merge() {
    if (checked.length < 2) return;
    const [destination, ...sources] = checked;
    await action.run("/incidents/merge", {
      body: { destination_incident_id: destination, source_incident_ids: sources },
      successMessage: `Merged ${sources.length} into ${destination}`,
    });
    setChecked([]);
    reload();
  }

  async function removeSelected() {
    await action.run("/incidents/bulk/delete", {
      body: { incident_ids: checked },
      successMessage: `Deleted ${checked.length} incident(s)`,
    });
    setChecked([]);
    reload();
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Incidents</h1>
          <p className="mt-1 text-sm text-slate-500">Alerts grouped into things worth working.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="input w-40 py-1.5 text-sm"
            value={range}
            onChange={(e) => setRange(Number(e.target.value))}
          >
            {RANGES.map((r) => (
              <option key={r.label} value={r.hours}>
                {r.label}
              </option>
            ))}
          </select>
          <GatedAction
            capability={can("incidents.create")}
            busy={action.busy}
            onClick={() => setShowCreate((v) => !v)}
          >
            <Plus className="h-3.5 w-3.5" />
            Create incident
          </GatedAction>
        </div>
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

      {showCreate ? (
        <section className="card-pad space-y-3">
          <h2 className="text-sm font-semibold text-slate-200">New incident</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <input
              className="input"
              placeholder="Name"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
            <input
              className="input"
              placeholder="Summary"
              value={draft.summary}
              onChange={(e) => setDraft({ ...draft, summary: e.target.value })}
            />
          </div>
          <div className="flex gap-2">
            <GatedAction
              capability={can("incidents.create")}
              busy={action.busy}
              onClick={createIncident}
            >
              Create
            </GatedAction>
            <button className="btn" onClick={() => setShowCreate(false)}>
              Cancel
            </button>
          </div>
        </section>
      ) : null}

      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      <div className="flex gap-6">
        <FacetSidebar
          facets={data?.facets ?? []}
          selection={selection}
          onChange={setSelection}
          loading={loading}
        />

        <div className="min-w-0 flex-1 space-y-3">
          {checked.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-surface-border bg-surface-overlay/50 px-3 py-2">
              <span className="text-xs text-slate-400">{checked.length} selected</span>
              <GatedAction
                capability={can("incidents.merge")}
                busy={action.busy}
                variant="plain"
                onClick={merge}
              >
                <GitMerge className="h-3.5 w-3.5" />
                Merge
              </GatedAction>
              <GatedAction
                capability={can("incidents.delete")}
                busy={action.busy}
                variant="danger"
                onClick={removeSelected}
              >
                <Trash2 className="h-3.5 w-3.5" />
                Delete
              </GatedAction>
              <button className="btn" onClick={() => setChecked([])}>
                Clear
              </button>
              {checked.length >= 2 ? (
                <span className="text-xs text-slate-600">
                  Merge folds the rest into the first one selected.
                </span>
              ) : null}
            </div>
          ) : null}

          <div className="card overflow-hidden">
            {loading && !data ? (
              <Spinner />
            ) : rows.length === 0 ? (
              <EmptyState
                title="No incidents match"
                hint={
                  Object.keys(selection).length > 0
                    ? "Reset the filters on the left to widen the view."
                    : "Keep has not correlated anything yet for this client."
                }
              />
            ) : (
              <table className="w-full">
                <thead className="bg-surface-overlay/40">
                  <tr>
                    <th className="th w-8">
                      <input
                        type="checkbox"
                        checked={allChecked}
                        onChange={() => setChecked(allChecked ? [] : rows.map((r) => r.id))}
                        className="h-3.5 w-3.5 rounded border-surface-border bg-surface-base accent-accent"
                      />
                    </th>
                    <th className="th">Incident</th>
                    <th className="th">Status</th>
                    <th className="th">Alerts</th>
                    <th className="th">Sources</th>
                    <th className="th">Services</th>
                    <th className="th">Assignee</th>
                    <th className="th">Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((incident) => (
                    <tr key={incident.id} className="row">
                      <td className="td">
                        <input
                          type="checkbox"
                          checked={checked.includes(incident.id)}
                          onChange={() =>
                            setChecked(
                              checked.includes(incident.id)
                                ? checked.filter((id) => id !== incident.id)
                                : [...checked, incident.id],
                            )
                          }
                          className="h-3.5 w-3.5 rounded border-surface-border bg-surface-base accent-accent"
                        />
                      </td>
                      <td className="td">
                        <div className="flex items-center gap-2">
                          <SeverityBadge severity={incident.severity} />
                          <Link
                            href={`/incidents/${incident.id}`}
                            className="font-medium text-slate-100 hover:text-accent"
                          >
                            {incident.name}
                          </Link>
                        </div>
                        {incident.summary ? (
                          <p className="mt-0.5 line-clamp-1 max-w-xl text-xs text-slate-600">
                            {incident.summary}
                          </p>
                        ) : null}
                        <div className="mt-1 flex flex-wrap gap-1">
                          {incident.is_candidate ? <span className="chip">candidate</span> : null}
                          {incident.is_predicted ? <span className="chip">AI-predicted</span> : null}
                          {incident.rule_id ? <span className="chip">linked</span> : null}
                        </div>
                      </td>
                      <td className="td">
                        <StatusDot status={incident.status} />
                      </td>
                      <td className="td tabular-nums">{incident.alerts_count}</td>
                      <td className="td">
                        <div className="flex flex-wrap gap-1">
                          {incident.sources.map((s) => (
                            <span key={s} className="chip">
                              {s}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="td">
                        <div className="flex flex-wrap gap-1">
                          {incident.services.slice(0, 3).map((s) => (
                            <span key={s} className="chip">
                              {s}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="td text-xs">
                        {incident.assignee ?? <span className="text-slate-600">unassigned</span>}
                      </td>
                      <td className="td">
                        <RelativeTime value={incident.last_seen_at} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {data ? (
            <p className="text-xs text-slate-600">
              Showing {rows.length} of {data.meta.total} incidents.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
