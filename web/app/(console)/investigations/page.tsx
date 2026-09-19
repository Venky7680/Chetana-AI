"use client";

import { useState } from "react";
import Link from "next/link";
import { Brain, ChevronDown, ChevronRight, Clock, Database, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import { EmptyState, ErrorState, RelativeTime, Spinner } from "@/components/ui";

/**
 * Every root cause analysis this client has had, in one place.
 *
 * Investigations used to live only on the incident they belonged to, which
 * meant the only way to see what the AI had concluded was to already know which
 * incident to open. This is the list view: what was asked, what was found, how
 * confident, and — expandable — the evidence chain the gateway recorded.
 */

interface EvidenceCall {
  id: string;
  tool: string;
  params: Record<string, string>;
  status: "ok" | "refused" | "error";
  detail: string | null;
  result_bytes: number | null;
  duration_ms: number | null;
}

interface Investigation {
  id: string;
  incident_id: string | null;
  status: "queued" | "running" | "complete" | "failed" | "cancelled";
  requested_by: string;
  finding: string | null;
  error: string | null;
  model: string | null;
  evidence_used: number;
  duration_ms: number | null;
  created_at: string | null;
  evidence?: EvidenceCall[];
}

/** Pull one labelled section out of the structured finding. */
function section(finding: string | null, label: string): string | null {
  if (!finding) return null;
  const match = new RegExp(
    `^\\s*\\*{0,2}${label}\\*{0,2}\\s*:?\\s*\\*{0,2}\\s*([\\s\\S]*?)(?=\\n\\s*\\*{0,2}(?:ROOT CAUSE|CONFIDENCE|EVIDENCE|IMPACT|RECOMMENDED ACTION)\\b|$)`,
    "im",
  ).exec(finding);
  return match ? match[1].trim() || null : null;
}

function confidenceTone(value: string | null): string {
  const v = (value ?? "").toLowerCase();
  if (v.startsWith("high")) return "text-emerald-400";
  if (v.startsWith("medium")) return "text-amber-400";
  if (v.startsWith("low")) return "text-sev-high";
  return "text-slate-500";
}

export default function InvestigationsPage() {
  const { tenant } = useSession();
  const { data, error, loading, reload } = useApi<{ items: Investigation[] }>("/investigations", {
    query: { limit: 100 },
  });
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, Investigation>>({});

  const items = Array.isArray(data?.items) ? data.items : [];

  async function toggle(id: string) {
    if (open === id) {
      setOpen(null);
      return;
    }
    setOpen(id);
    if (!detail[id]) {
      try {
        const full = await api<Investigation>(`/investigations/${id}`);
        setDetail((prev) => ({ ...prev, [id]: full }));
      } catch {
        // The row stays collapsed-but-selected; the summary is still readable.
      }
    }
  }

  if (loading && !data) return <Spinner label="Reading investigations" />;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Root cause analyses</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Every investigation run for {tenant?.name ?? "this client"}. Expand one to see the
          evidence chain — the gateway&apos;s own record of what the engine read, which is what
          makes a finding checkable rather than merely plausible.
        </p>
      </header>

      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      {items.length === 0 ? (
        <EmptyState
          title="No investigations yet"
          hint="Open an incident and use Investigate. Each run is recorded here with its evidence."
        />
      ) : (
        <div className="card overflow-hidden">
          {items.map((item) => {
            const expanded = open === item.id;
            const full = detail[item.id];
            const rootCause = section(item.finding, "ROOT CAUSE");
            const confidence = section(item.finding, "CONFIDENCE");
            const running = item.status === "queued" || item.status === "running";

            return (
              <div key={item.id} className="border-b border-surface-border last:border-b-0">
                <button
                  onClick={() => toggle(item.id)}
                  className="flex w-full items-start gap-3 px-5 py-3.5 text-left hover:bg-surface-overlay/30"
                >
                  {expanded ? (
                    <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-slate-600" />
                  ) : (
                    <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-600" />
                  )}

                  <div className="min-w-0 flex-1">
                    {item.status === "failed" ? (
                      <p className="flex items-start gap-1.5 text-sm text-sev-critical">
                        <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                        {item.error ?? "The investigation failed."}
                      </p>
                    ) : running ? (
                      <p className="text-sm text-slate-400">Investigating…</p>
                    ) : (
                      <p className="text-sm text-slate-200">
                        {rootCause ?? item.finding?.slice(0, 200) ?? "No finding recorded."}
                      </p>
                    )}

                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-600">
                      {confidence ? (
                        <span className={confidenceTone(confidence)}>
                          {confidence.split(/[\s—-]/)[0]} confidence
                        </span>
                      ) : null}
                      {item.incident_id ? (
                        <Link
                          href={`/incidents/${encodeURIComponent(item.incident_id)}`}
                          className="hover:text-accent"
                          onClick={(e) => e.stopPropagation()}
                        >
                          incident
                        </Link>
                      ) : null}
                      <span className="inline-flex items-center gap-1">
                        <Database className="h-3 w-3" />
                        {item.evidence_used} reads
                      </span>
                      {item.duration_ms ? (
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {(item.duration_ms / 1000).toFixed(1)}s
                        </span>
                      ) : null}
                      <span>{item.requested_by}</span>
                      <RelativeTime value={item.created_at} />
                    </div>
                  </div>
                </button>

                {expanded ? (
                  <div className="space-y-4 border-t border-surface-border bg-surface-base/40 px-5 py-4">
                    {item.finding ? (
                      <div>
                        <h3 className="label mb-1">Full finding</h3>
                        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-400">
                          {item.finding}
                        </p>
                      </div>
                    ) : null}

                    {!full ? (
                      <Spinner label="Loading the evidence chain" />
                    ) : (full.evidence?.length ?? 0) === 0 ? (
                      <p className="text-xs text-slate-600">
                        No evidence calls recorded for this run.
                      </p>
                    ) : (
                      <div>
                        <h3 className="label mb-2 flex items-center gap-1.5">
                          <Database className="h-3 w-3" />
                          Evidence chain — {full.evidence?.length} gateway calls
                        </h3>
                        <table className="w-full">
                          <tbody>
                            {(full.evidence ?? []).map((call) => (
                              <tr key={call.id} className="row">
                                <td className="td font-mono text-xs text-slate-300">{call.tool}</td>
                                <td className="td max-w-md">
                                  <div className="flex flex-wrap gap-1">
                                    {Object.entries(call.params ?? {}).map(([k, v]) => (
                                      <span key={k} className="chip max-w-xs truncate font-mono">
                                        {k}={String(v)}
                                      </span>
                                    ))}
                                  </div>
                                </td>
                                <td className="td text-xs">
                                  {call.status === "ok" ? (
                                    <span className="text-emerald-400">
                                      ok{call.result_bytes ? ` · ${call.result_bytes} B` : ""}
                                    </span>
                                  ) : (
                                    <span className="text-sev-critical">
                                      {call.status}
                                      {call.detail ? ` — ${call.detail}` : ""}
                                    </span>
                                  )}
                                </td>
                                <td className="td tabular-nums text-xs text-slate-500">
                                  {call.duration_ms !== null ? `${call.duration_ms} ms` : "—"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    <p className="flex items-start gap-2 text-xs text-slate-600">
                      <Brain className="mt-0.5 h-3 w-3 shrink-0" />
                      <span>
                        {item.model ? (
                          <>
                            <span className="font-mono">{item.model}</span> ·{" "}
                          </>
                        ) : null}
                        the rows above were written by the evidence gateway as it served each
                        read, not reported by the model.
                      </span>
                    </p>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
