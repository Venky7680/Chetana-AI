"use client";

import { useApi } from "@/lib/session";
import type { TopologyService } from "@/lib/types";
import { TopologyEditor } from "@/components/TopologyEditor";
import { EmptyState, ErrorState, ProblemBanner, Spinner } from "@/components/ui";

interface Application {
  id: string;
  name: string;
  description?: string;
  services?: { id?: string; name?: string }[];
}

export default function TopologyPage() {
  const { data, error, loading, reload } = useApi<{
    services: TopologyService[];
    applications: Application[];
    problems?: string[];
  }>("/topology");

  if (loading && !data) return <Spinner label="Reading topology" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  const services = Array.isArray(data?.services) ? data.services : [];
  const applications = Array.isArray(data?.applications) ? data.applications : [];

  // Who depends on whom, inverted — "what breaks if this breaks" is the
  // question an operator actually has at 3am.
  const dependents = new Map<string, string[]>();
  for (const service of services) {
    for (const dep of service.dependencies ?? []) {
      const target = dep.serviceName ?? String(dep.serviceId ?? "");
      if (!target) continue;
      dependents.set(target, [...(dependents.get(target) ?? []), service.service]);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Topology</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Service dependencies as Keep understands them. This is what turns &quot;six services are
          alerting&quot; into &quot;one service is down and five depend on it&quot;.
        </p>
      </header>

      <ProblemBanner problems={data?.problems} />

      <TopologyEditor services={services} onChanged={reload} />

      {applications.length > 0 ? (
        <section className="card">
          <div className="border-b border-surface-border px-5 py-3.5">
            <h2 className="text-sm font-semibold text-slate-200">Applications</h2>
          </div>
          <div className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
            {applications.map((app) => (
              <div key={app.id} className="rounded-lg border border-surface-border px-4 py-3">
                <p className="text-sm font-medium text-slate-200">{app.name}</p>
                {app.description ? (
                  <p className="mt-0.5 text-xs text-slate-600">{app.description}</p>
                ) : null}
                <div className="mt-2 flex flex-wrap gap-1">
                  {(app.services ?? []).map((s, i) => (
                    <span key={`${s.name}-${i}`} className="chip">
                      {s.name ?? s.id}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="card">
        <div className="border-b border-surface-border px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-200">
            Services <span className="text-slate-600">({services.length})</span>
          </h2>
        </div>
        {services.length === 0 ? (
          <EmptyState
            title="No topology recorded"
            hint="Keep discovers this from providers that expose a service map. An alert-only setup has none — so declare the graph here with Add service, then connect the pieces with Add dependency."
          />
        ) : (
          <table className="w-full">
            <thead className="bg-surface-overlay/40">
              <tr>
                <th className="th">Service</th>
                <th className="th">Environment</th>
                <th className="th">Depends on</th>
                <th className="th">Breaks if this breaks</th>
              </tr>
            </thead>
            <tbody>
              {services.map((service) => (
                <tr key={String(service.id)} className="row">
                  <td className="td">
                    <p className="font-medium text-slate-200">
                      {service.display_name || service.service}
                    </p>
                    {service.description ? (
                      <p className="mt-0.5 text-xs text-slate-600">{service.description}</p>
                    ) : null}
                  </td>
                  <td className="td text-slate-400">{service.environment ?? "—"}</td>
                  <td className="td">
                    <div className="flex flex-wrap gap-1">
                      {(service.dependencies ?? []).length === 0 ? (
                        <span className="text-slate-600">—</span>
                      ) : (
                        (service.dependencies ?? []).map((dep, i) => (
                          <span key={i} className="chip">
                            {dep.serviceName ?? dep.serviceId}
                            {dep.protocol ? ` (${dep.protocol})` : ""}
                          </span>
                        ))
                      )}
                    </div>
                  </td>
                  <td className="td">
                    <div className="flex flex-wrap gap-1">
                      {(dependents.get(service.service) ?? []).length === 0 ? (
                        <span className="text-slate-600">—</span>
                      ) : (
                        (dependents.get(service.service) ?? []).map((name) => (
                          <span key={name} className="chip border-amber-800/50 text-amber-400/80">
                            {name}
                          </span>
                        ))
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
