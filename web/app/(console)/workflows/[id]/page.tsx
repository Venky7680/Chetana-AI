"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, Play } from "lucide-react";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import type { WorkflowDetail } from "@/lib/types";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { EmptyState, ErrorState, GatedAction, RelativeTime, Spinner } from "@/components/ui";

const RUN_STATUS_TONE: Record<string, string> = {
  success: "text-emerald-400",
  error: "text-sev-critical",
  failed: "text-sev-critical",
  in_progress: "text-sev-warning",
  timeout: "text-sev-warning",
};

export default function WorkflowDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useSession();
  const { data, error, loading, reload } = useApi<WorkflowDetail>(`/workflows/${id}/detail`);
  const action = useAction();

  if (loading && !data) return <Spinner label="Loading workflow" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const { workflow, definition, runs } = data;

  async function run() {
    await action.run(`/workflows/${id}/run`, {
      body: { reason: "Manual run from workflow detail" },
      successMessage: "Workflow started",
    });
    reload();
  }

  return (
    <div className="space-y-6">
      <Link
        href="/workflows"
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-accent"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Workflows
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold text-slate-100">{workflow.name}</h1>
            {workflow.disabled ? <span className="chip">disabled</span> : null}
            {workflow.revision ? <span className="chip">rev {workflow.revision}</span> : null}
          </div>
          {workflow.description ? (
            <p className="mt-2 max-w-3xl text-sm text-slate-400">{workflow.description}</p>
          ) : null}
          <p className="mt-2 font-mono text-xs text-slate-600">{workflow.id}</p>
        </div>
        <GatedAction capability={can("workflows.run")} busy={action.busy} onClick={run}>
          <Play className="h-3.5 w-3.5" />
          Run now
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

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="card lg:col-span-2">
          <div className="border-b border-surface-border px-5 py-3.5">
            <h2 className="text-sm font-semibold text-slate-200">Definition</h2>
          </div>
          {definition ? (
            <pre className="max-h-[32rem] overflow-auto p-5 font-mono text-xs leading-relaxed text-slate-300">
              {definition}
            </pre>
          ) : (
            <EmptyState title="No YAML returned" hint="Keep did not expose a raw definition for this workflow." />
          )}
        </section>

        <div className="space-y-6">
          <section className="card-pad space-y-2 text-sm">
            <h2 className="text-sm font-semibold text-slate-200">Wiring</h2>
            <div>
              <p className="label mb-1">Triggers</p>
              <div className="flex flex-wrap gap-1">
                {workflow.triggers.length === 0 ? (
                  <span className="text-xs text-slate-600">manual only</span>
                ) : (
                  workflow.triggers.map((trigger, i) => (
                    <span key={i} className="chip">
                      {String((trigger as { type?: string }).type ?? "manual")}
                    </span>
                  ))
                )}
              </div>
            </div>
            <div>
              <p className="label mb-1">Providers it touches</p>
              <div className="flex flex-wrap gap-1">
                {workflow.providers.length === 0 ? (
                  <span className="text-xs text-slate-600">none</span>
                ) : (
                  workflow.providers.map((provider, i) => (
                    <span key={i} className="chip">
                      {provider.type ?? "unknown"}
                    </span>
                  ))
                )}
              </div>
            </div>
            {workflow.created_by ? (
              <div className="flex justify-between gap-3 pt-1">
                <span className="text-slate-500">Author</span>
                <span className="truncate text-slate-300">{workflow.created_by}</span>
              </div>
            ) : null}
          </section>

          <section className="card">
            <div className="border-b border-surface-border px-5 py-3.5">
              <h2 className="text-sm font-semibold text-slate-200">
                Runs <span className="text-slate-600">({runs.length})</span>
              </h2>
            </div>
            {runs.length === 0 ? (
              <EmptyState title="Never run" />
            ) : (
              <ul className="divide-y divide-surface-border/70">
                {runs.slice(0, 20).map((entry, index) => {
                  const status = String(entry.status ?? "unknown");
                  return (
                    <li key={String(entry.id ?? index)} className="px-5 py-2.5 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className={RUN_STATUS_TONE[status] ?? "text-slate-400"}>{status}</span>
                        <RelativeTime value={(entry.started as string) ?? null} />
                      </div>
                      {entry.execution_time !== undefined ? (
                        <p className="mt-0.5 text-slate-600">{String(entry.execution_time)}s</p>
                      ) : null}
                      {entry.triggered_by ? (
                        <p className="mt-0.5 truncate text-slate-600">{String(entry.triggered_by)}</p>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
