"use client";

import { use, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Tag } from "lucide-react";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import type { AlertDetail } from "@/lib/types";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import {
  EmptyState,
  ErrorState,
  GatedAction,
  RelativeTime,
  SeverityBadge,
  Spinner,
  StatusDot,
} from "@/components/ui";

export default function AlertDetailPage({
  params,
}: {
  params: Promise<{ fingerprint: string }>;
}) {
  const { fingerprint } = use(params);
  const { can } = useSession();
  const { data, error, loading, reload } = useApi<AlertDetail>(`/alerts/${fingerprint}/detail`);
  const action = useAction();
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");

  if (loading && !data) return <Spinner label="Loading alert" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const { alert, occurrences, audit } = data;
  const labels = Object.entries(alert.labels ?? {});

  async function enrich() {
    if (!key.trim()) return;
    await action.run("/alerts/enrich", {
      body: { fingerprint, enrichments: { [key.trim()]: value } },
      successMessage: `Added ${key.trim()}`,
    });
    setKey("");
    setValue("");
    reload();
  }

  return (
    <div className="space-y-6">
      <Link
        href="/alerts"
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-accent"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Alerts
      </Link>

      <header>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold text-slate-100">{alert.name}</h1>
          <SeverityBadge severity={alert.severity} />
          <StatusDot status={alert.status} />
        </div>
        {alert.description ? (
          <p className="mt-2 max-w-3xl text-sm text-slate-400">{alert.description}</p>
        ) : null}
        <p className="mt-2 font-mono text-xs text-slate-600">{alert.fingerprint}</p>
      </header>

      {action.parked ? (
        <ApprovalBanner approval={action.parked} message={action.message} onDismiss={action.reset} />
      ) : null}
      {action.error ? <ErrorState message={action.error} /> : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section className="card">
            <div className="border-b border-surface-border px-5 py-3.5">
              <h2 className="text-sm font-semibold text-slate-200">Labels from the source</h2>
            </div>
            {labels.length === 0 ? (
              <EmptyState title="No labels" hint="This provider sent no label set." />
            ) : (
              <table className="w-full">
                <tbody>
                  {labels.map(([name, val]) => (
                    <tr key={name} className="row">
                      <td className="td w-1/3 font-mono text-xs text-slate-500">{name}</td>
                      <td className="td break-all font-mono text-xs text-slate-300">
                        {typeof val === "object" ? JSON.stringify(val) : String(val)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card">
            <div className="border-b border-surface-border px-5 py-3.5">
              <h2 className="text-sm font-semibold text-slate-200">
                Occurrences <span className="text-slate-600">({occurrences.length})</span>
              </h2>
            </div>
            {occurrences.length === 0 ? (
              <EmptyState title="No history recorded" />
            ) : (
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="th">Seen</th>
                    <th className="th">Status</th>
                    <th className="th">Severity</th>
                  </tr>
                </thead>
                <tbody>
                  {occurrences.slice(0, 30).map((occurrence, index) => (
                    <tr key={`${occurrence.last_received}-${index}`} className="row">
                      <td className="td">
                        <RelativeTime value={occurrence.last_received} />
                      </td>
                      <td className="td">
                        <StatusDot status={occurrence.status} />
                      </td>
                      <td className="td">
                        <SeverityBadge severity={occurrence.severity} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card">
            <div className="border-b border-surface-border px-5 py-3.5">
              <h2 className="text-sm font-semibold text-slate-200">Audit trail (Keep)</h2>
            </div>
            {audit.length === 0 ? (
              <EmptyState title="No audit entries" />
            ) : (
              <ul className="divide-y divide-surface-border/70">
                {audit.slice(0, 25).map((entry, index) => (
                  <li key={index} className="px-5 py-2.5 text-xs">
                    <span className="text-slate-300">{String(entry.action ?? "event")}</span>
                    <span className="text-slate-600">
                      {" · "}
                      {String(entry.user_id ?? "keep")}
                      {entry.timestamp ? ` · ${new Date(String(entry.timestamp)).toLocaleString()}` : ""}
                    </span>
                    {entry.description ? (
                      <p className="mt-0.5 text-slate-600">{String(entry.description)}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <div className="space-y-6">
          <section className="card-pad space-y-2 text-sm">
            <h2 className="text-sm font-semibold text-slate-200">Attribution</h2>
            <Field label="Service" value={alert.service} />
            <Field label="Environment" value={alert.environment} />
            <Field label="Source" value={alert.source.join(", ") || null} />
            <Field label="Assignee" value={alert.assignee} />
            <div className="flex justify-between gap-3">
              <span className="text-slate-500">First seen</span>
              <RelativeTime value={alert.last_received} />
            </div>
            {alert.url ? (
              <a
                href={alert.url}
                target="_blank"
                rel="noreferrer"
                className="block pt-1 text-xs text-accent hover:underline"
              >
                Open in source system
              </a>
            ) : null}
          </section>

          <section className="card-pad">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <Tag className="h-4 w-4 text-slate-500" />
              Enrich
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              Writes a field back onto the alert in Keep, stamped with your identity. Tier R1 —
              reversible, so it runs without approval.
            </p>
            {alert.enriched_fields?.length ? (
              <div className="mt-3 flex flex-wrap gap-1">
                {alert.enriched_fields.map((field) => (
                  <span key={field} className="chip font-mono">
                    {field}
                  </span>
                ))}
              </div>
            ) : null}
            <div className="mt-3 space-y-2">
              <input
                className="input"
                placeholder="field (e.g. runbook)"
                value={key}
                onChange={(e) => setKey(e.target.value)}
              />
              <input
                className="input"
                placeholder="value (e.g. RB-003)"
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
              <GatedAction capability={can("alerts.enrich")} busy={action.busy} onClick={enrich}>
                Add field
              </GatedAction>
            </div>
            {action.message && !action.parked ? (
              <p className="mt-2 text-xs text-emerald-400">{action.message}</p>
            ) : null}
          </section>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className="truncate text-slate-300">{value ?? "—"}</span>
    </div>
  );
}
