"use client";

import Link from "next/link";
import { ArrowRight, TrendingDown } from "lucide-react";
import { useApi, useSession } from "@/lib/session";
import type { Overview } from "@/lib/types";
import {
  EmptyState,
  ErrorState,
  RelativeTime,
  SeverityBadge,
  Spinner,
  StatCard,
  StatusDot,
} from "@/components/ui";

export default function OverviewPage() {
  const { tenant } = useSession();
  const { data, error, loading, reload } = useApi<Overview>("/overview");

  if (loading && !data) return <Spinner label="Reading Keep" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const { stats, autonomy } = data;

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">{tenant?.name ?? "Overview"}</h1>
          <p className="mt-1 text-sm text-slate-500">
            Live from Keep · autonomy ceiling R{autonomy.effective_ceiling}
            {autonomy.pending_approvals > 0 ? (
              <>
                {" · "}
                <Link href="/approvals" className="text-accent hover:underline">
                  {autonomy.pending_approvals} awaiting approval
                </Link>
              </>
            ) : null}
          </p>
        </div>
      </header>

      {!data.reachable ? (
        <ErrorState message={`Keep is not fully reachable: ${data.problems.join("; ")}`} onRetry={reload} />
      ) : null}

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Open incidents"
          value={stats.incidents_open}
          hint={`${stats.incidents_total} total`}
          tone={stats.critical_open > 0 ? "critical" : "default"}
        />
        <StatCard
          label="Firing alerts"
          value={stats.alerts_firing}
          hint={`${stats.alerts_total} in window`}
          tone={stats.alerts_firing > 0 ? "warn" : "good"}
        />
        <StatCard
          label="Noise reduction"
          value={`${stats.noise_reduction_pct}%`}
          hint={`${stats.alerts_correlated} alerts → ${stats.incidents_total} incidents`}
          // Zero noise reduction is not good news, and colouring it green says
          // it is. The tone follows the number rather than the label.
          tone={stats.noise_reduction_pct > 0 ? "good" : "default"}
        />
        <StatCard
          label="Unassigned"
          value={stats.unassigned_incidents}
          hint="Open incidents with no owner"
          tone={stats.unassigned_incidents > 0 ? "warn" : "good"}
        />
      </section>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="card lg:col-span-2">
          <div className="flex items-center justify-between border-b border-surface-border px-5 py-3.5">
            <h2 className="text-sm font-semibold text-slate-200">Incidents needing attention</h2>
            <Link href="/incidents" className="text-xs text-accent hover:underline">
              All incidents
            </Link>
          </div>
          {data.top_incidents.length === 0 ? (
            <EmptyState title="Nothing open" hint="Every correlated incident is resolved." />
          ) : (
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">Incident</th>
                  <th className="th">Severity</th>
                  <th className="th">Alerts</th>
                  <th className="th">Last seen</th>
                  <th className="th" />
                </tr>
              </thead>
              <tbody>
                {data.top_incidents.map((incident) => (
                  <tr key={incident.id} className="row">
                    <td className="td">
                      <Link
                        href={`/incidents/${incident.id}`}
                        className="font-medium text-slate-100 hover:text-accent"
                      >
                        {incident.name}
                      </Link>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <StatusDot status={incident.status} />
                        {incident.is_predicted ? <span className="chip">AI-predicted</span> : null}
                        {incident.services.slice(0, 2).map((service) => (
                          <span key={service} className="chip">
                            {service}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="td">
                      <SeverityBadge severity={incident.severity} />
                    </td>
                    <td className="td tabular-nums">{incident.alerts_count}</td>
                    <td className="td">
                      <RelativeTime value={incident.last_seen_at} />
                    </td>
                    <td className="td">
                      <Link href={`/incidents/${incident.id}`} className="text-slate-500 hover:text-accent">
                        <ArrowRight className="h-4 w-4" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="space-y-6">
          <div className="card">
            <div className="border-b border-surface-border px-5 py-3.5">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                <TrendingDown className="h-4 w-4 text-slate-500" />
                Noisiest services
              </h2>
            </div>
            <div className="space-y-2.5 p-5">
              {data.noisiest_services.length === 0 ? (
                <p className="text-sm text-slate-600">No alerts in the window.</p>
              ) : (
                data.noisiest_services.map((service) => {
                  const max = data.noisiest_services[0].alerts || 1;
                  return (
                    <div key={service.name}>
                      <div className="flex items-baseline justify-between text-xs">
                        <span className="truncate text-slate-300">{service.name}</span>
                        <span className="tabular-nums text-slate-500">{service.alerts}</span>
                      </div>
                      <div className="mt-1 h-1 rounded-full bg-surface-overlay">
                        <div
                          className="h-1 rounded-full bg-accent/70"
                          style={{ width: `${Math.round((service.alerts / max) * 100)}%` }}
                        />
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <div className="card">
            <div className="flex items-center justify-between border-b border-surface-border px-5 py-3.5">
              <h2 className="text-sm font-semibold text-slate-200">Latest alerts</h2>
              <Link href="/alerts" className="text-xs text-accent hover:underline">
                All
              </Link>
            </div>
            <ul className="divide-y divide-surface-border/70">
              {data.recent_alerts.slice(0, 7).map((alert) => (
                <li key={alert.fingerprint} className="px-5 py-2.5">
                  <div className="flex items-start justify-between gap-3">
                    <p className="truncate text-sm text-slate-300">{alert.name}</p>
                    <SeverityBadge severity={alert.severity} />
                  </div>
                  <p className="mt-0.5 text-xs text-slate-600">
                    {alert.service ?? "unattributed"} · <RelativeTime value={alert.last_received} />
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </div>
  );
}
