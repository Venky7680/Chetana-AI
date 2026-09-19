"use client";

import { useApi, useSession } from "@/lib/session";
import type { EstateRow } from "@/lib/types";
import { EmptyState, ErrorState, Spinner, StatCard } from "@/components/ui";

export default function EstatePage() {
  const { switchTenant } = useSession();
  const { data, error, loading, reload } = useApi<{
    totals: { tenants: number; unreachable: number; incidents_open: number; alerts_firing: number; critical_open: number };
    tenants: EstateRow[];
  }>("/estate", { noTenant: true });

  if (loading && !data) return <Spinner label="Polling every client" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-[-0.015em] text-ink">Operations Overview</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Every client you are entitled to, worst first. Unreachable Keep instances sort to the top.
        </p>
      </header>

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Clients" value={data.totals.tenants} />
        <StatCard
          label="Unreachable"
          value={data.totals.unreachable}
          tone={data.totals.unreachable > 0 ? "critical" : "good"}
        />
        <StatCard
          label="Open incidents"
          value={data.totals.incidents_open}
          tone={data.totals.critical_open > 0 ? "warn" : "default"}
        />
        <StatCard label="Firing alerts" value={data.totals.alerts_firing} />
      </section>

      <div className="card overflow-hidden">
        {data.tenants.length === 0 ? (
          <EmptyState title="No clients configured" hint="Add tenants to CHETANA_TENANTS_JSON." />
        ) : (
          <table className="w-full">
            <thead className="bg-surface-overlay/40">
              <tr>
                <th className="th">Client</th>
                <th className="th">Keep</th>
                <th className="th">Open incidents</th>
                <th className="th">Critical</th>
                <th className="th">Firing alerts</th>
                <th className="th">Noise reduction</th>
                <th className="th">Approvals</th>
                <th className="th" />
              </tr>
            </thead>
            <tbody>
              {data.tenants.map((row) => (
                <tr key={row.tenant.id} className="row">
                  <td className="td">
                    <p className="font-medium text-slate-100">{row.tenant.name}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {row.tenant.tags.map((tag) => (
                        <span key={tag} className="chip">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="td">
                    {row.reachable ? (
                      <span className="text-xs text-emerald-400">reachable</span>
                    ) : (
                      <span className="text-xs text-sev-critical" title={row.problems.join("; ")}>
                        unreachable
                      </span>
                    )}
                  </td>
                  <td className="td tabular-nums">{row.stats.incidents_open ?? "—"}</td>
                  <td className="td tabular-nums">
                    <span className={row.stats.critical_open ? "text-sev-critical" : undefined}>
                      {row.stats.critical_open ?? "—"}
                    </span>
                  </td>
                  <td className="td tabular-nums">{row.stats.alerts_firing ?? "—"}</td>
                  <td className="td tabular-nums">
                    {row.stats.noise_reduction_pct !== undefined
                      ? `${row.stats.noise_reduction_pct}%`
                      : "—"}
                  </td>
                  <td className="td tabular-nums">{row.pending_approvals ?? 0}</td>
                  <td className="td">
                    <button className="btn" onClick={() => switchTenant(row.tenant.id)}>
                      Open
                    </button>
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
