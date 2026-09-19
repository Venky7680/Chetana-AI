"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import type { ProviderCatalogueEntry } from "@/lib/types";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { ProviderInstall } from "@/components/ProviderInstall";
import { EmptyState, ErrorState, GatedAction, Spinner } from "@/components/ui";

interface InstalledProvider {
  id: string;
  type: string;
  details?: { name?: string };
  validatedScopes?: Record<string, unknown>;
  last_alert_received?: string;
}


export default function ProvidersPage() {
  const providers = useApi<{
    installed_providers: InstalledProvider[];
    available_count: number;
    categories: string[];
  }>("/providers");
  const catalogue = useApi<ProviderCatalogueEntry[]>("/providers/catalogue");
  const { can } = useSession();
  const action = useAction();
  const [showCatalogue, setShowCatalogue] = useState(false);
  const [connecting, setConnecting] = useState(false);

  if (providers.error) return <ErrorState message={providers.error} onRetry={providers.reload} />;
  if (providers.loading && !providers.data) return <Spinner />;

  const installed = Array.isArray(providers.data?.installed_providers)
    ? providers.data.installed_providers
    : [];

  async function install(payload: {
    provider_id: string;
    provider_name: string;
    provider_type: string;
    pulling_enabled: boolean;
    config: Record<string, string | boolean>;
  }) {
    const result = await action.run("/providers/install", {
      body: payload,
      successMessage: `${payload.provider_name} connected`,
    });
    if (result !== null) setConnecting(false);
    providers.reload();
    return result;
  }

  async function uninstall(provider: InstalledProvider) {
    await action.run(`/providers/${provider.type}/${provider.id}`, {
      method: "DELETE",
      successMessage: `${provider.details?.name ?? provider.type} disconnected`,
    });
    providers.reload();
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Providers</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Where this client&apos;s telemetry comes from. Chetana federates telemetry rather than
            owning it — these are the systems of record, and Keep is the plane that unifies them.
          </p>
        </div>
        <GatedAction
          capability={can("providers.install")}
          busy={action.busy}
          onClick={() => setConnecting((v) => !v)}
        >
          <Plus className="h-3.5 w-3.5" />
          Connect a source
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

      {connecting ? (
        <ProviderInstall
          catalogue={Array.isArray(catalogue.data) ? catalogue.data : []}
          capability={can("providers.install")}
          busy={action.busy}
          onInstall={install}
          onCancel={() => setConnecting(false)}
        />
      ) : null}

      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-border px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-200">
            Installed <span className="text-slate-600">({installed.length})</span>
          </h2>
          <button className="btn" onClick={() => setShowCatalogue((v) => !v)}>
            {showCatalogue ? "Hide" : "Browse"} catalogue ({providers.data?.available_count ?? 0})
          </button>
        </div>
        {installed.length === 0 ? (
          <EmptyState
            title="No providers installed"
            hint="Use Connect a source above, or send an alert through a provider's webhook and Keep registers it automatically."
          />
        ) : (
          <div className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
            {installed.map((provider) => (
              <div key={provider.id} className="rounded-lg border border-surface-border px-4 py-3">
                <p className="text-sm font-medium text-slate-200">
                  {provider.details?.name ?? provider.type}
                </p>
                <p className="mt-0.5 text-xs text-slate-600">{provider.type}</p>
                {provider.last_alert_received ? (
                  <p className="mt-1.5 text-xs text-slate-500">
                    Last alert {new Date(provider.last_alert_received).toLocaleString()}
                  </p>
                ) : null}
                <div className="mt-2">
                  <GatedAction
                    capability={can("providers.delete")}
                    busy={action.busy}
                    variant="danger"
                    onClick={() => uninstall(provider)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Disconnect
                  </GatedAction>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {showCatalogue ? <Catalogue /> : null}

    </div>
  );
}

function Catalogue() {
  const { data, loading } = useApi<ProviderCatalogueEntry[]>("/providers/catalogue");
  const [query, setQuery] = useState("");

  if (loading && !data) return <Spinner label="Loading catalogue" />;
  const entries = (data ?? []).filter((entry) =>
    query
      ? `${entry.display_name} ${entry.type} ${entry.categories.join(" ")}`
          .toLowerCase()
          .includes(query.toLowerCase())
      : true,
  );

  return (
    <section className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-border px-5 py-3.5">
        <h2 className="text-sm font-semibold text-slate-200">Available in Keep</h2>
        <input
          className="input w-56"
          placeholder="Search providers"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="grid max-h-96 gap-2 overflow-y-auto p-5 sm:grid-cols-2 lg:grid-cols-3">
        {entries.map((entry) => (
          <div key={entry.type} className="rounded-lg border border-surface-border px-3 py-2">
            <p className="truncate text-sm text-slate-200">{entry.display_name}</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {entry.supports_webhook ? <span className="chip">webhook</span> : null}
              {entry.can_query ? <span className="chip">query</span> : null}
              {entry.can_notify ? <span className="chip">notify</span> : null}
            </div>
          </div>
        ))}
        {entries.length === 0 ? (
          <p className="col-span-full text-sm text-slate-600">Nothing matches that search.</p>
        ) : null}
      </div>
      <p className="border-t border-surface-border px-5 py-3 text-xs text-slate-600">
        Use <span className="text-slate-400">Connect a source</span> above to install any of these.
        Credentials go to this client&apos;s Keep secret manager and nowhere else.
      </p>
    </section>
  );
}
