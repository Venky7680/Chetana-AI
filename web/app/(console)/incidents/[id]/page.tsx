"use client";

import { use, useState } from "react";
import Link from "next/link";
import { ArrowLeft, MessageSquare, Play } from "lucide-react";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import type { Envelope, IncidentDetail, Workflow } from "@/lib/types";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { InvestigationPanel } from "@/components/InvestigationPanel";
import {
  EmptyState,
  ErrorState,
  GatedAction,
  RelativeTime,
  SeverityBadge,
  Spinner,
  StatusDot,
} from "@/components/ui";

const STATUS_ACTIONS = ["acknowledged", "resolved", "firing"];

export default function IncidentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useSession();
  const { data, error, loading, reload } = useApi<IncidentDetail>(`/incidents/${id}/detail`);
  const { data: workflows } = useApi<Envelope<Workflow>>("/workflows");
  const action = useAction();
  const [comment, setComment] = useState("");

  if (loading && !data) return <Spinner label="Loading incident" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const { incident, alerts, workflow_executions: runs } = data;

  async function changeStatus(status: string) {
    await action.run(`/incidents/${id}/status`, {
      body: { status },
      successMessage: `Status set to ${status}`,
    });
    reload();
  }

  async function submitComment() {
    if (!comment.trim()) return;
    await action.run(`/incidents/${id}/comment`, {
      body: { comment: comment.trim() },
      successMessage: "Comment added",
    });
    setComment("");
    reload();
  }

  async function runWorkflow(workflowId: string) {
    await action.run(`/workflows/${workflowId}/run`, {
      body: { incident_id: id, reason: `Triggered from incident ${id}` },
      successMessage: "Workflow started",
    });
    reload();
  }

  return (
    <div className="space-y-6">
      <Link href="/incidents" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-accent">
        <ArrowLeft className="h-3.5 w-3.5" />
        Incidents
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold text-slate-100">{incident.name}</h1>
            <SeverityBadge severity={incident.severity} />
            <StatusDot status={incident.status} />
          </div>
          {incident.summary ? (
            <p className="mt-2 max-w-3xl text-sm text-slate-400">{incident.summary}</p>
          ) : null}
          <p className="mt-2 font-mono text-xs text-slate-600">{incident.id}</p>
        </div>

        <div className="flex flex-wrap gap-2">
          {STATUS_ACTIONS.filter((s) => s !== incident.status).map((status) => (
            <GatedAction
              key={status}
              capability={can("incidents.status")}
              busy={action.busy}
              variant="plain"
              onClick={() => changeStatus(status)}
            >
              Mark {status}
            </GatedAction>
          ))}
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

      <InvestigationPanel incidentId={id} />

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="card lg:col-span-2">
          <div className="border-b border-surface-border px-5 py-3.5">
            <h2 className="text-sm font-semibold text-slate-200">
              Correlated alerts <span className="text-slate-600">({alerts.length})</span>
            </h2>
          </div>
          {alerts.length === 0 ? (
            <EmptyState title="No alerts attached" />
          ) : (
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">Alert</th>
                  <th className="th">Severity</th>
                  <th className="th">Source</th>
                  <th className="th">Last seen</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.fingerprint} className="row">
                    <td className="td">
                      <p className="text-slate-200">{alert.name}</p>
                      <p className="mt-0.5 text-xs text-slate-600">
                        {alert.service ?? "unattributed"}
                        {alert.environment ? ` · ${alert.environment}` : ""}
                      </p>
                    </td>
                    <td className="td">
                      <SeverityBadge severity={alert.severity} />
                    </td>
                    <td className="td">
                      <div className="flex flex-wrap gap-1">
                        {alert.source.map((s) => (
                          <span key={s} className="chip">
                            {s}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="td">
                      <RelativeTime value={alert.last_received} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="space-y-6">
          <div className="card-pad">
            <h2 className="text-sm font-semibold text-slate-200">Remediation</h2>
            <p className="mt-1 text-xs text-slate-500">
              Running a workflow reaches into the client estate, so it is tier R2 — it executes only
              within the tenant&apos;s autonomy ceiling, or after approval.
            </p>
            <div className="mt-4 space-y-2">
              {(workflows?.items ?? [])
                .filter((workflow) => !workflow.disabled)
                .slice(0, 6)
                .map((workflow) => (
                  <div
                    key={workflow.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-surface-border px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm text-slate-200">{workflow.name}</p>
                      <p className="truncate text-xs text-slate-600">
                        {workflow.providers.map((p) => p.type).filter(Boolean).join(", ") || "no provider"}
                      </p>
                    </div>
                    <GatedAction
                      capability={can("workflows.run")}
                      busy={action.busy}
                      onClick={() => runWorkflow(workflow.id)}
                    >
                      <Play className="h-3.5 w-3.5" />
                      Run
                    </GatedAction>
                  </div>
                ))}
              {(workflows?.items ?? []).length === 0 ? (
                <p className="text-xs text-slate-600">No workflows defined in Keep yet.</p>
              ) : null}
            </div>
          </div>

          <div className="card-pad">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <MessageSquare className="h-4 w-4 text-slate-500" />
              Add a note
            </h2>
            <textarea
              className="input mt-3 h-24 resize-none"
              placeholder="What did you find, what did you do?"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
            <GatedAction
              capability={can("incidents.comment")}
              busy={action.busy}
              onClick={submitComment}
            >
              Post note
            </GatedAction>
          </div>

          <div className="card">
            <div className="border-b border-surface-border px-5 py-3.5">
              <h2 className="text-sm font-semibold text-slate-200">Workflow runs</h2>
            </div>
            {runs.length === 0 ? (
              <EmptyState title="Nothing has run" hint="Automation triggered here will appear in this list." />
            ) : (
              <ul className="divide-y divide-surface-border/70">
                {runs.slice(0, 8).map((run, index) => (
                  <li key={String(run.workflow_execution_id ?? index)} className="px-5 py-2.5 text-xs">
                    <p className="text-slate-300">{String(run.workflow_id ?? "workflow")}</p>
                    <p className="mt-0.5 text-slate-600">
                      {String(run.status ?? "unknown")} · {String(run.requested_by ?? "system")}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
