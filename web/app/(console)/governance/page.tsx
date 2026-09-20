"use client";

import { useState } from "react";
import { useApi, useSession } from "@/lib/session";
import type { AuditEntry, Capability } from "@/lib/types";
import { EmptyState, ErrorState, Spinner, TierBadge } from "@/components/ui";

/**
 * Which body of past tickets the investigation engine may cite, and whether
 * those tickets really happened. That second question is the one a client's
 * security reviewer asks, and its answer should not live only in a container's
 * startup log.
 */
interface Corpus {
  name?: string;
  kind?: string;
  tickets?: number;
  patterns_loaded?: number;
  window?: string;
  caveat?: string;
}

/** What the investigation engine is permitted to read. Deliberately shown next
 *  to the operation allowlist: an LLM's reach should be as inspectable as the
 *  console's, and a client's security reviewer will ask for exactly this. */
interface EvidenceTool {
  name: string;
  description: string;
  kind: string;
  operation_id: string | null;
  parameters: { name: string; description: string; required: boolean }[];
}

const DECISION_STYLES: Record<string, string> = {
  execute: "border-emerald-700/50 bg-emerald-500/10 text-emerald-400",
  approval_required: "border-amber-700/50 bg-amber-500/10 text-amber-400",
  denied: "border-slate-700 bg-surface-overlay text-slate-500",
};

export default function GovernancePage() {
  const { tenant } = useSession();
  const [tab, setTab] = useState<"allowlist" | "evidence" | "audit">("allowlist");

  const capabilities = useApi<{ operations: Capability[]; effective_ceiling: number }>("/capabilities");
  const audit = useApi<AuditEntry[]>("/audit", { query: { limit: 200 } });
  const evidence = useApi<{ tools: EvidenceTool[] }>("/evidence/tools");
  // Which corpus this client may cite is tenant data, so it lives behind
  // auth rather than on the public tool-contract endpoint.
  const corpus = useApi<{ owned: boolean; corpus: Corpus | null }>("/precedents");

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Governance</h1>
        <p className="mt-1 text-sm text-slate-500">
          Exactly what this console is permitted to do in {tenant?.name ?? "this client"}&apos;s Keep,
          and everything it has tried. The allowlist is the product surface, not a secret.
        </p>
      </header>

      <div className="flex gap-1.5">
        {(["allowlist", "evidence", "audit"] as const).map((key) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`rounded-md border px-3 py-1.5 text-sm capitalize transition ${
              tab === key
                ? "border-accent/50 bg-accent/10 text-accent"
                : "border-surface-border text-slate-500 hover:text-slate-300"
            }`}
          >
            {key === "allowlist"
              ? "Operation allowlist"
              : key === "evidence"
                ? "AI evidence tools"
                : "Audit trail"}
          </button>
        ))}
      </div>

      {tab === "allowlist" ? (
        <AllowlistTable state={capabilities} />
      ) : tab === "evidence" ? (
        <EvidenceTools state={evidence} corpus={corpus.data ?? null} />
      ) : (
        <AuditTable state={audit} />
      )}
    </div>
  );
}

function AllowlistTable({
  state,
}: {
  state: ReturnType<typeof useApi<{ operations: Capability[]; effective_ceiling: number }>>;
}) {
  const { data, error, loading, reload } = state;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading && !data) return <Spinner />;
  if (!data) return null;

  // Derived rather than read from the role, so the sentence describes what this
  // viewer will actually experience. An admin is not parked, and promising them
  // an approval step that never appears is the kind of wrong documentation
  // nobody notices until a client reads it.
  const bypassing = data.operations.some(
    (op) => op.tier > data.effective_ceiling && op.decision === "execute",
  );

  return (
    <>
      <p className="text-xs text-slate-500">
        Effective autonomy ceiling: <span className="text-slate-300">R{data.effective_ceiling}</span> —
        the stricter of the deployment ceiling and what this client signed off on.{" "}
        {bypassing ? (
          <>
            You are an admin, so nothing is parked for you: actions above the ceiling execute and
            are recorded in the audit trail as an{" "}
            <span className="text-sev-warning">admin override</span>.
          </>
        ) : (
          <>Anything above it is parked for approval rather than refused.</>
        )}
      </p>
      <div className="card overflow-hidden">
        <table className="w-full">
          <thead className="bg-surface-overlay/40">
            <tr>
              <th className="th">Operation</th>
              <th className="th">Tier</th>
              <th className="th">Min role</th>
              <th className="th">For you</th>
              <th className="th">Why</th>
            </tr>
          </thead>
          <tbody>
            {data.operations.map((op) => (
              <tr key={op.operation_id} className="row">
                <td className="td">
                  <p className="font-mono text-xs text-slate-300">{op.operation_id}</p>
                  <p className="mt-0.5 text-xs text-slate-600">{op.summary}</p>
                </td>
                <td className="td">
                  <TierBadge tier={op.tier} />
                </td>
                <td className="td capitalize text-slate-400">{op.min_role}</td>
                <td className="td">
                  <span
                    className={`inline-flex rounded border px-2 py-0.5 text-[11px] ${
                      DECISION_STYLES[op.decision] ?? DECISION_STYLES.denied
                    }`}
                  >
                    {op.decision.replace("_", " ")}
                  </span>
                </td>
                <td className="td max-w-md text-xs text-slate-600">{op.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function AuditTable({ state }: { state: ReturnType<typeof useApi<AuditEntry[]>> }) {
  const { data, error, loading, reload } = state;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading && !data) return <Spinner />;
  const items = data ?? [];

  if (items.length === 0) {
    return (
      <div className="card">
        <EmptyState
          title="No activity yet"
          hint="Every write, refusal and parked action is recorded here and written to disk as NDJSON."
        />
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <table className="w-full">
        <thead className="bg-surface-overlay/40">
          <tr>
            <th className="th">When</th>
            <th className="th">Actor</th>
            <th className="th">Operation</th>
            <th className="th">Decision</th>
            <th className="th">Reason</th>
          </tr>
        </thead>
        <tbody>
          {items.map((entry, index) => (
            <tr key={`${entry.ts}-${index}`} className="row">
              <td className="td whitespace-nowrap text-xs text-slate-500">
                {new Date(entry.ts).toLocaleString()}
              </td>
              <td className="td text-xs text-slate-400">{entry.actor}</td>
              <td className="td">
                <span className="font-mono text-xs text-slate-300">{entry.operation_id}</span>
                <TierBadge tier={entry.tier} />
              </td>
              <td className="td text-xs capitalize text-slate-300">
                {entry.decision.replace(/_/g, " ")}
                {/* An admin executing above the ceiling is still an execution,
                    but it is the one a client asks about later, so it must not
                    read identically to an ordinary approved action. */}
                {entry.detail?.override === "admin" ? (
                  <span className="mt-1 inline-flex rounded border border-sev-warning/50 bg-sev-warning/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-sev-warning">
                    admin override
                  </span>
                ) : null}
                {entry.status !== "ok" ? (
                  <span className="mt-0.5 block text-slate-600">{entry.status}</span>
                ) : null}
              </td>
              <td className="td max-w-md text-xs text-slate-600">{entry.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceTools({
  state,
  corpus,
}: {
  state: ReturnType<typeof useApi<{ tools: EvidenceTool[] }>>;
  corpus: { owned: boolean; corpus: Corpus | null } | null;
}) {
  const { data, error, loading, reload } = state;
  if (loading && !data) return <Spinner label="Reading the evidence toolset" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  const tools = Array.isArray(data?.tools) ? data.tools : [];
  if (tools.length === 0) return <EmptyState title="No evidence tools registered" />;

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-sm text-slate-500">
        HolmesGPT holds no credentials for this estate. Everything it can see during an
        investigation is listed here, each one reached through a short-lived token scoped to a
        single investigation and a single client, and each one recorded in the audit trail above.
      </p>

      <CorpusCard corpus={corpus?.corpus ?? null} owned={corpus?.owned ?? false} />

      <div className="card overflow-hidden">
        <table className="w-full">
          <thead className="bg-surface-overlay/40">
            <tr>
              <th className="th">Tool</th>
              <th className="th">What it returns</th>
              <th className="th">Arguments</th>
              <th className="th">Backed by</th>
            </tr>
          </thead>
          <tbody>
            {tools.map((tool) => (
              <tr key={tool.name} className="row align-top">
                <td className="td font-mono text-xs text-slate-200">{tool.name}</td>
                <td className="td max-w-lg text-xs text-slate-500">{tool.description}</td>
                <td className="td">
                  <div className="flex flex-wrap gap-1">
                    {tool.parameters.length === 0 ? (
                      <span className="text-slate-600">—</span>
                    ) : (
                      tool.parameters.map((p) => (
                        <span key={p.name} className="chip font-mono" title={p.description}>
                          {p.name}
                          {p.required ? "*" : ""}
                        </span>
                      ))
                    )}
                  </div>
                </td>
                <td className="td text-xs">
                  {tool.operation_id ? (
                    <span className="font-mono text-slate-400">{tool.operation_id}</span>
                  ) : (
                    <span className="text-slate-500">{tool.kind}</span>
                  )}
                  <span className="mt-0.5 block text-slate-600">read-only (R0)</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


function CorpusCard({ corpus, owned }: { corpus: Corpus | null; owned: boolean }) {
  if (!corpus) {
    return (
      <div className="glass rounded-xl px-4 py-3">
        <h3 className="text-xs font-semibold text-slate-300">No precedent corpus loaded</h3>
        <p className="mt-1 text-xs text-slate-500">
          The engine reasons only from live evidence. It cannot cite how a symptom was resolved
          before, because it has no ticket history to search.
        </p>
      </div>
    );
  }

  const synthetic = (corpus.kind ?? "").toLowerCase() === "synthetic";
  return (
    <div
      className={`rounded-lg border px-4 py-3 ${
        synthetic
          ? "border-sev-warning/30 bg-sev-warning/5"
          : "border-white/10 bg-white/[0.05]"
      }`}
    >
      <h3 className="flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-300">
        {owned ? "Precedent corpus — this client\u2019s own history" : "Precedent corpus — shared demo"}
        <span
          className={`chip ${synthetic ? "border-sev-warning/40 text-sev-warning" : "border-emerald-700/40 text-emerald-400"}`}
        >
          {synthetic ? "synthetic" : (corpus.kind ?? "unknown")}
        </span>
      </h3>
      <p className="mt-1 text-xs text-slate-400">
        {corpus.name}
        {corpus.patterns_loaded ? ` · ${corpus.patterns_loaded} patterns` : ""}
        {corpus.tickets ? ` from ${corpus.tickets.toLocaleString()} tickets` : ""}
        {corpus.window ? ` · ${corpus.window}` : ""}
      </p>
      {corpus.caveat ? (
        <p className="mt-1.5 max-w-3xl text-xs text-slate-500">{corpus.caveat}</p>
      ) : null}
      {synthetic ? (
        <p className="mt-1.5 max-w-3xl text-xs text-sev-warning/90">
          Every search result carries this provenance into the model, and the engine is
          instructed to repeat it in any finding that relies on a precedent. Replace the corpus
          with a real ticket export to remove this warning.
        </p>
      ) : null}
    </div>
  );
}
