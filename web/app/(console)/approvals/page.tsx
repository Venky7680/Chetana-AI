"use client";

import { useState } from "react";
import { Check } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import type { ApprovalRequest } from "@/lib/types";
import { EmptyState, ErrorState, Spinner, TierBadge } from "@/components/ui";

export default function ApprovalsPage() {
  const { me } = useSession();
  const { data, error, loading, reload } = useApi<ApprovalRequest[]>("/approvals");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const isApprover = (me?.role_level ?? 0) >= 30;

  async function approve(id: string) {
    setBusyId(id);
    setFailure(null);
    try {
      await api(`/approvals/${id}/approve`, { method: "POST", body: { note: "" } });
      reload();
    } catch (err) {
      setFailure(err instanceof Error ? err.message : "Approval failed");
    } finally {
      setBusyId(null);
    }
  }

  const items = Array.isArray(data) ? data : [];

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Approvals</h1>
        <p className="mt-1 text-sm text-slate-500">
          Actions the gateway parked because they exceed this client&apos;s autonomy ceiling. Tier R3
          needs two distinct principals, and a requester can never approve their own request.
        </p>
      </header>

      {!isApprover ? (
        <p className="rounded-lg border border-surface-border bg-surface-overlay/40 px-3 py-2 text-sm text-slate-400">
          Your role can raise approval requests but not release them. An approver or admin has to act.
        </p>
      ) : null}

      {failure ? <ErrorState message={failure} /> : null}
      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      <div className="card overflow-hidden">
        {loading && !data ? (
          <Spinner />
        ) : items.length === 0 ? (
          <EmptyState
            title="Nothing waiting"
            hint="Parked actions show up here with who asked and what they wanted to do."
          />
        ) : (
          <ul className="divide-y divide-surface-border/70">
            {items.map((request) => {
              const canApprove =
                isApprover && !request.satisfied && request.requested_by !== me?.email;
              return (
                <li key={request.id} className="flex flex-wrap items-start justify-between gap-4 p-5">
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 text-sm font-medium text-slate-100">
                      {request.operation_id}
                      <TierBadge tier={request.tier} />
                    </p>
                    {request.note ? (
                      <p className="mt-1 text-sm text-slate-400">{request.note}</p>
                    ) : null}
                    {Object.keys(request.target.path_params).length > 0 ? (
                      <p className="mt-1 font-mono text-xs text-slate-600">
                        {Object.entries(request.target.path_params)
                          .map(([key, value]) => `${key}=${value}`)
                          .join("  ")}
                      </p>
                    ) : null}
                    <p className="mt-2 text-xs text-slate-500">
                      Requested by {request.requested_by} ·{" "}
                      {new Date(request.created_at).toLocaleString()} · expires{" "}
                      {new Date(request.expires_at).toLocaleTimeString()}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {request.approvals.length}/{request.approvals_needed} approvals
                      {request.approvals.length > 0 ? ` — ${request.approvals.join(", ")}` : ""}
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    {request.satisfied ? (
                      <span className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-700/40 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-400">
                        <Check className="h-3.5 w-3.5" />
                        Released — re-run the action to execute
                      </span>
                    ) : (
                      <button
                        className="btn-primary"
                        disabled={!canApprove || busyId === request.id}
                        title={
                          request.requested_by === me?.email
                            ? "You raised this request; someone else has to approve it"
                            : undefined
                        }
                        onClick={() => approve(request.id)}
                      >
                        Approve
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
