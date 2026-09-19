"use client";

import { Sparkles } from "lucide-react";
import { useApi, useSession } from "@/lib/session";
import type { Incident, Envelope } from "@/lib/types";
import { AiModelSettings, type AiConfig } from "@/components/AiModelSettings";
import { EmptyState, ErrorState, Spinner } from "@/components/ui";

/**
 * Keep's AI plugins train correlation models on this tenant's own history.
 *
 * An earlier version of this page said the models could only be configured in
 * Keep's own UI. That was wrong: Keep does expose them over REST, but with
 * include_in_schema=False, so they are absent from its API docs rather than
 * absent from the product. They are tuned here now, like everything else.
 */
export default function AiPluginsPage() {
  const { tenant } = useSession();
  const { data, loading } = useApi<Envelope<Incident>>("/incidents", { query: { limit: 200 } });
  const ai = useApi<{
    algorithm_configs: AiConfig[];
    alerts_count: number;
    incidents_count: number;
  }>("/ai");

  const incidents = data?.items ?? [];
  const candidates = incidents.filter((i) => i.is_candidate);
  const predicted = incidents.filter((i) => i.is_predicted);
  const models = Array.isArray(ai.data?.algorithm_configs) ? ai.data.algorithm_configs : [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">AI Plugins</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Keep&apos;s AI layer learns correlation patterns from this client&apos;s own alert
          history and proposes groupings a static rule would miss. Below is what it has actually
          produced for {tenant?.name ?? "this client"}.
        </p>
      </header>

      {ai.error ? <ErrorState message={ai.error} onRetry={ai.reload} /> : null}

      {ai.loading && !ai.data ? (
        <Spinner label="Reading the AI layer" />
      ) : models.length === 0 ? (
        <EmptyState
          title="No AI models available for this client"
          hint="Keep's AI layer reports no models. It needs a body of alert history before the models become useful, and some are licensed separately."
        />
      ) : (
        <div className="space-y-4">
          {models.map((model) => (
            <AiModelSettings key={model.algorithm_id ?? model.id} config={model} onSaved={ai.reload} />
          ))}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel
          title="Candidate incidents"
          blurb="Groupings the model proposed that nobody has confirmed yet. Confirming one turns it into a real incident."
          incidents={candidates}
          loading={loading && !data}
        />
        <Panel
          title="Predicted incidents"
          blurb="Incidents the model expects to develop, based on how similar alert patterns have played out before."
          incidents={predicted}
          loading={loading && !data}
        />
      </div>
    </div>
  );
}

function Panel({
  title,
  blurb,
  incidents,
  loading,
}: {
  title: string;
  blurb: string;
  incidents: Incident[];
  loading: boolean;
}) {
  return (
    <section className="card">
      <div className="border-b border-surface-border px-5 py-3.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <Sparkles className="h-4 w-4 text-slate-500" />
          {title}
          <span className="text-slate-600">({incidents.length})</span>
        </h2>
        <p className="mt-0.5 text-xs text-slate-600">{blurb}</p>
      </div>
      {loading ? (
        <Spinner />
      ) : incidents.length === 0 ? (
        <EmptyState
          title="Nothing proposed"
          hint="The model needs a body of history before it suggests anything."
        />
      ) : (
        <ul className="divide-y divide-surface-border/70">
          {incidents.map((incident) => (
            <li key={incident.id} className="px-5 py-3">
              <a href={`/incidents/${incident.id}`} className="text-sm text-slate-200 hover:text-accent">
                {incident.name}
              </a>
              <p className="mt-0.5 text-xs text-slate-600">
                {incident.alerts_count} alert(s)
                {incident.services.length ? ` · ${incident.services.join(", ")}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
