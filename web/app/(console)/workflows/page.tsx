"use client";

import { useState } from "react";
import Link from "next/link";
import { Pencil, Play, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import type { Envelope, Workflow, WorkflowDetail } from "@/lib/types";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { WorkflowEditor } from "@/components/WorkflowEditor";
import { EmptyState, ErrorState, GatedAction, RelativeTime, Spinner } from "@/components/ui";

export default function WorkflowsPage() {
  const { can } = useSession();
  const { data, error, loading, reload } = useApi<Envelope<Workflow>>("/workflows");
  const action = useAction();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<{ id: string; name: string; yaml: string } | null>(null);
  const [loadingEditor, setLoadingEditor] = useState(false);

  const items = Array.isArray(data?.items) ? data.items : [];

  async function run(workflowId: string) {
    await action.run(`/workflows/${workflowId}/run`, {
      body: { reason: "Manual run from console" },
      successMessage: "Workflow started",
    });
    reload();
  }

  async function create(yaml: string) {
    const result = await action.run("/workflows", {
      body: { yaml, reason: "Authored in the Chetana console" },
      successMessage: "Workflow created in Keep",
    });
    if (result !== null) setCreating(false);
    reload();
  }

  async function update(yaml: string) {
    if (!editing) return;
    const result = await action.run(`/workflows/${editing.id}`, {
      method: "PUT",
      body: { yaml, reason: "Edited in the Chetana console" },
      successMessage: "Workflow updated",
    });
    if (result !== null) setEditing(null);
    reload();
  }

  async function openEditor(workflow: Workflow) {
    setLoadingEditor(true);
    try {
      // Fetch the YAML Keep actually holds, so an edit starts from the truth
      // rather than from something reconstructed in the browser.
      const detail = await api<WorkflowDetail>(`/workflows/${workflow.id}/detail`);
      setEditing({
        id: workflow.id,
        name: workflow.name,
        yaml: detail.definition || "",
      });
    } catch {
      setEditing({ id: workflow.id, name: workflow.name, yaml: "" });
    } finally {
      setLoadingEditor(false);
    }
  }

  async function remove(workflow: Workflow) {
    await action.run(`/workflows/${workflow.id}`, {
      method: "DELETE",
      successMessage: `Deleted ${workflow.name}`,
    });
    reload();
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Workflows</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Automation that runs against the client estate. Write it here — it is stored in Keep and
            executed by Keep, but you never have to leave the console to author it.
          </p>
        </div>
        <GatedAction
          capability={can("workflows.create")}
          busy={action.busy}
          onClick={() => {
            setEditing(null);
            setCreating((v) => !v);
          }}
        >
          <Plus className="h-3.5 w-3.5" />
          New workflow
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
      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      {creating ? (
        <WorkflowEditor
          title="New workflow"
          capability={can("workflows.create")}
          busy={action.busy}
          onSubmit={create}
          onCancel={() => setCreating(false)}
        />
      ) : null}

      {editing ? (
        <WorkflowEditor
          title={`Edit ${editing.name}`}
          initialYaml={editing.yaml}
          showTemplates={false}
          capability={can("workflows.update")}
          busy={action.busy}
          onSubmit={update}
          onCancel={() => setEditing(null)}
        />
      ) : null}

      {loadingEditor ? <Spinner label="Loading the definition from Keep" /> : null}

      <div className="card overflow-hidden">
        {loading && !data ? (
          <Spinner />
        ) : items.length === 0 ? (
          <EmptyState
            title="No workflows yet"
            hint="Use New workflow above — there are starter templates, and nothing has to be defined in Keep's own UI."
          />
        ) : (
          <table className="w-full">
            <thead className="bg-surface-overlay/40">
              <tr>
                <th className="th">Workflow</th>
                <th className="th">Providers</th>
                <th className="th">Trigger</th>
                <th className="th">Last run</th>
                <th className="th" />
              </tr>
            </thead>
            <tbody>
              {items.map((workflow) => (
                <tr key={workflow.id} className="row">
                  <td className="td">
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/workflows/${encodeURIComponent(workflow.id)}`}
                        className="font-medium text-slate-200 hover:text-accent"
                      >
                        {workflow.name}
                      </Link>
                      {workflow.disabled ? <span className="chip">disabled</span> : null}
                    </div>
                    {workflow.description ? (
                      <p className="mt-0.5 max-w-xl text-xs text-slate-600">{workflow.description}</p>
                    ) : null}
                    <span className="truncate-mono">{workflow.id}</span>
                  </td>
                  <td className="td">
                    <div className="flex flex-wrap gap-1">
                      {(workflow.providers ?? []).map((provider, index) => (
                        <span key={`${provider.type}-${index}`} className="chip">
                          {provider.type ?? "unknown"}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="td">
                    <div className="flex flex-wrap gap-1">
                      {(workflow.triggers ?? []).map((trigger, index) => (
                        <span key={index} className="chip">
                          {String((trigger as { type?: string }).type ?? "manual")}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="td">
                    <RelativeTime value={workflow.last_execution_time} />
                    {workflow.last_execution_status ? (
                      <span className="mt-0.5 block text-xs text-slate-600">
                        {workflow.last_execution_status}
                      </span>
                    ) : null}
                  </td>
                  <td className="td">
                    <div className="flex flex-wrap gap-1.5">
                      <GatedAction
                        capability={can("workflows.run")}
                        busy={action.busy}
                        onClick={() => run(workflow.id)}
                      >
                        <Play className="h-3.5 w-3.5" />
                        Run
                      </GatedAction>
                      <GatedAction
                        capability={can("workflows.update")}
                        busy={action.busy}
                        variant="plain"
                        onClick={() => {
                          setCreating(false);
                          openEditor(workflow);
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        Edit
                      </GatedAction>
                      <GatedAction
                        capability={can("workflows.delete")}
                        busy={action.busy}
                        variant="danger"
                        onClick={() => remove(workflow)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </GatedAction>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
