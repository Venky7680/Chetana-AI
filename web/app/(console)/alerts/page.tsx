"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Filter, Search } from "lucide-react";
import { useApi } from "@/lib/session";
import type { Alert, Envelope, Preset } from "@/lib/types";
import { applyFacets, FacetSidebar, type Facet, type FacetSelection } from "@/components/Facets";
import { SavedViews } from "@/components/SavedViews";
import {
  EmptyState,
  ErrorState,
  RelativeTime,
  SeverityBadge,
  Spinner,
  StatusDot,
} from "@/components/ui";

const CEL_EXAMPLES = [
  { label: "Critical only", cel: 'severity == "critical"' },
  { label: "Unassigned", cel: "assignee == null" },
  { label: "Payments path", cel: 'service.contains("payments") || service.contains("ledger")' },
  { label: "Prometheus", cel: 'providerType == "prometheus"' },
];

type Faceted = Envelope<Alert> & { facets: Facet[] };

export default function FeedPage() {
  const [selection, setSelection] = useState<FacetSelection>({});
  const [search, setSearch] = useState("");
  const [cel, setCel] = useState("");
  const [appliedCel, setAppliedCel] = useState("");

  const { data, error, loading, reload } = useApi<Faceted>("/alerts", {
    query: { limit: 300, cel: appliedCel || undefined },
  });
  const presets = useApi<Preset[]>("/presets");

  const rows = useMemo(() => {
    let items = data?.items ?? [];
    if (search) {
      const needle = search.toLowerCase();
      items = items.filter((a) =>
        `${a.name} ${a.service ?? ""} ${a.description ?? ""}`.toLowerCase().includes(needle),
      );
    }
    return applyFacets(items, selection, (alert, key) => {
      switch (key) {
        case "status":
          return alert.status;
        case "severity":
          return alert.severity;
        case "source":
          return alert.source.length ? alert.source : "None";
        case "service":
          return alert.service ?? "None";
        case "environment":
          return alert.environment ?? "None";
        case "assignee":
          return alert.assignee ?? "None";
        default:
          return "None";
      }
    });
  }, [data, selection, search]);

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Feed</h1>
        <p className="mt-1 text-sm text-slate-500">
          Every alert Keep has ingested and deduplicated, across this client&apos;s providers.
        </p>
      </header>

      <section className="card-pad space-y-3">
        <div className="flex items-center gap-2">
          <Filter className="h-3.5 w-3.5 text-slate-500" />
          <span className="label">CEL filter — evaluated by Keep, not the browser</span>
        </div>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setAppliedCel(cel);
          }}
        >
          <input
            className="input font-mono text-xs"
            placeholder='severity == "critical" && service.startsWith("checkout")'
            value={cel}
            onChange={(e) => setCel(e.target.value)}
          />
          <button type="submit" className="btn-primary shrink-0">
            Apply
          </button>
          {appliedCel ? (
            <button
              type="button"
              className="btn shrink-0"
              onClick={() => {
                setCel("");
                setAppliedCel("");
              }}
            >
              Clear
            </button>
          ) : null}
        </form>
        <div className="flex flex-wrap gap-1.5">
          {CEL_EXAMPLES.map((example) => (
            <button
              key={example.label}
              onClick={() => {
                setCel(example.cel);
                setAppliedCel(example.cel);
              }}
              className="rounded-md border border-surface-border px-2 py-1 text-xs text-slate-500 transition hover:border-slate-500 hover:text-slate-300"
            >
              {example.label}
            </button>
          ))}
        </div>

        <div className="border-t border-surface-border pt-3">
          <SavedViews
            presets={presets.data ?? []}
            currentCel={cel}
            activeCel={appliedCel}
            onApply={(next) => {
              setCel(next);
              setAppliedCel(next);
            }}
            onChanged={presets.reload}
          />
        </div>
      </section>

      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      <div className="flex gap-6">
        <FacetSidebar
          facets={data?.facets ?? []}
          selection={selection}
          onChange={setSelection}
          loading={loading}
        />

        <div className="min-w-0 flex-1 space-y-3">
          <div className="relative w-72">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            <input
              className="input pl-8"
              placeholder="Filter loaded rows"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="card overflow-hidden">
            {loading && !data ? (
              <Spinner />
            ) : rows.length === 0 ? (
              <EmptyState
                title="No alerts match"
                hint={
                  appliedCel
                    ? "The CEL filter matched nothing in Keep."
                    : "Nothing ingested for this client yet, or everything is filtered out."
                }
              />
            ) : (
              <table className="w-full">
                <thead className="bg-surface-overlay/40">
                  <tr>
                    <th className="th">Alert</th>
                    <th className="th">Status</th>
                    <th className="th">Service</th>
                    <th className="th">Source</th>
                    <th className="th">Last received</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((alert) => (
                    <tr key={alert.fingerprint} className="row">
                      <td className="td">
                        <div className="flex items-center gap-2">
                          <SeverityBadge severity={alert.severity} />
                          <Link
                            href={`/alerts/${encodeURIComponent(alert.fingerprint)}`}
                            className="font-medium text-slate-200 hover:text-accent"
                          >
                            {alert.name}
                          </Link>
                        </div>
                        {alert.description ? (
                          <p className="mt-0.5 line-clamp-1 max-w-xl text-xs text-slate-600">
                            {alert.description}
                          </p>
                        ) : null}
                      </td>
                      <td className="td">
                        <StatusDot status={alert.status} />
                      </td>
                      <td className="td">
                        {alert.service ?? <span className="text-slate-600">—</span>}
                        {alert.environment ? (
                          <span className="mt-0.5 block text-xs text-slate-600">
                            {alert.environment}
                          </span>
                        ) : null}
                      </td>
                      <td className="td">
                        <div className="flex flex-wrap gap-1">
                          {alert.source.map((source) => (
                            <span key={source} className="chip">
                              {source}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="td">
                        <RelativeTime value={alert.last_received} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {data ? (
            <p className="text-xs text-slate-600">
              Showing {rows.length} of {data.meta.total} alerts Keep reports.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
