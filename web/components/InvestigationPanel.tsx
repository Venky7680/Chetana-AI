"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { ErrorState, Spinner } from "@/components/ui";

/**
 * Layer 5 on the incident page.
 *
 * The finding is the headline, but the evidence chain below it is what makes
 * this usable in anger. Those rows are written by the BFF's evidence gateway as
 * it serves each read — they are not Holmes' account of what it did. So if the
 * model claims it checked a metric and there is no row for it, the row count
 * disagrees and the panel says so. An engineer who cannot audit the reasoning
 * will not trust it twice.
 */

interface EvidenceCall {
  id: string;
  tool: string;
  params: Record<string, string>;
  status: "ok" | "refused" | "error";
  status_code: number | null;
  detail: string | null;
  result_bytes: number | null;
  duration_ms: number | null;
  at: string | null;
}

interface Investigation {
  id: string;
  status: "queued" | "running" | "complete" | "failed" | "cancelled";
  requested_by: string;
  finding: string | null;
  error: string | null;
  model: string | null;
  evidence_used: number;
  evidence_budget: number;
  created_at: string | null;
  duration_ms: number | null;
  evidence?: EvidenceCall[];
  reported_tool_calls?: { tool: string; description: string }[];
}

interface Capabilities {
  configured: boolean;
  reachable: boolean;
  tenant_enabled: boolean;
  may_investigate: boolean;
  min_role: string;
  model: string | null;
  tools: string[];
  evidence_budget: number;
  hourly_limit: number;
}

const SECTIONS = [
  "ROOT CAUSE",
  "CONFIDENCE",
  "EVIDENCE",
  "IMPACT",
  "RECOMMENDED ACTION",
] as const;

/** Split the structured answer into its labelled parts, tolerating a model that
 *  wanders off the format rather than throwing the whole finding away. */
function parseFinding(text: string): { label: string; body: string }[] {
  const found: { label: string; index: number }[] = [];
  for (const label of SECTIONS) {
    const match = new RegExp(`^\\s*\\*{0,2}${label}\\*{0,2}\\s*:`, "im").exec(text);
    if (match) found.push({ label, index: match.index });
  }
  if (found.length === 0) return [{ label: "", body: text.trim() }];

  found.sort((a, b) => a.index - b.index);
  return found.map((entry, i) => {
    const slice = text.slice(entry.index, found[i + 1]?.index ?? text.length);
    const body = slice.replace(new RegExp(`^\\s*\\*{0,2}${entry.label}\\*{0,2}\\s*:`, "i"), "");
    return { label: entry.label, body: body.trim() };
  });
}

function confidenceTone(value: string): string {
  const v = value.toLowerCase();
  if (v.startsWith("high")) return "text-emerald-400";
  if (v.startsWith("medium")) return "text-amber-400";
  return "text-slate-400";
}

export function InvestigationPanel({ incidentId }: { incidentId: string }) {
  const { can } = useSession();
  void can;
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [current, setCurrent] = useState<Investigation | null>(null);
  const [history, setHistory] = useState<Investigation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [showEvidence, setShowEvidence] = useState(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      const result = await api<{ items: Investigation[] }>("/investigations", {
        query: { incident_id: incidentId, limit: 10 },
      });
      const items = Array.isArray(result?.items) ? result.items : [];
      setHistory(items);
      return items;
    } catch {
      return [];
    }
  }, [incidentId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const capabilities = await api<Capabilities>("/investigations/capabilities");
        if (!cancelled) setCaps(capabilities);
      } catch {
        if (!cancelled) setCaps(null);
      }
      const items = await loadHistory();
      // Resume watching an investigation that was already in flight — a page
      // reload should not orphan a run that is still costing money.
      const live = items.find((i) => i.status === "queued" || i.status === "running");
      if (!cancelled && live) void poll(live.id);
      else if (!cancelled && items[0]) void refresh(items[0].id);
    })();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidentId]);

  async function refresh(id: string): Promise<Investigation | null> {
    try {
      const record = await api<Investigation>(`/investigations/${id}`);
      setCurrent(record);
      return record;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the investigation");
      return null;
    }
  }

  async function poll(id: string) {
    const record = await refresh(id);
    if (record && (record.status === "queued" || record.status === "running")) {
      timer.current = setTimeout(() => void poll(id), 2500);
    } else {
      void loadHistory();
    }
  }

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const record = await api<Investigation>("/investigations", {
        method: "POST",
        body: { incident_id: incidentId },
      });
      setCurrent(record);
      void poll(record.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the investigation");
    } finally {
      setStarting(false);
    }
  }

  if (!caps || !caps.configured) return null;

  const running = current?.status === "queued" || current?.status === "running";
  const blocked =
    !caps.reachable
      ? "The investigation engine is configured but not responding. Check the holmes container."
      : !caps.tenant_enabled
        ? "AI investigation is not enabled for this client."
        : !caps.may_investigate
          ? `Starting an investigation requires the ${caps.min_role} role.`
          : null;

  const evidence = current?.evidence ?? [];
  const served = evidence.filter((c) => c.status === "ok").length;
  // Compare like with like. `attempted` is every call the gateway handled,
  // including the ones it refused or that errored — a failed read is still a
  // real read attempt. And only count Holmes' claims against OUR toolset;
  // its reported_tool_calls also include its own internal tools, which made
  // the first version of this banner cry wolf on a perfectly good run.
  const attempted = evidence.length;
  const claimed = (current?.reported_tool_calls ?? []).filter((t) =>
    (t.tool ?? "").startsWith("chetana_"),
  ).length;
  const discrepancy = current?.status === "complete" && claimed > attempted;

  return (
    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-border px-5 py-3.5">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Brain className="h-4 w-4 text-accent" />
            AI investigation
          </h2>
          <p className="mt-0.5 text-xs text-slate-600">
            HolmesGPT reads this estate only through Chetana&apos;s evidence gateway — no
            credentials, {caps.tools.length} read-only tools, every call audited below.
          </p>
        </div>
        <button
          className="btn btn-primary"
          disabled={Boolean(blocked) || running || starting}
          onClick={start}
          title={blocked ?? undefined}
        >
          {running ? "Investigating…" : starting ? "Starting…" : current ? "Re-investigate" : "Investigate"}
        </button>
      </div>

      {blocked ? (
        <p className="border-b border-surface-border bg-amber-500/5 px-5 py-2.5 text-xs text-amber-400">
          {blocked}
        </p>
      ) : null}
      {error ? (
        <div className="px-5 py-3">
          <ErrorState message={error} />
        </div>
      ) : null}

      {!current && !running ? (
        <div className="px-5 py-6 text-sm text-slate-500">
          No investigation has been run for this incident yet.
          {caps.model ? (
            <span className="mt-1 block text-xs text-slate-600">
              Model: <span className="font-mono">{caps.model}</span> · budget{" "}
              {caps.evidence_budget} reads · limit {caps.hourly_limit}/hour per client
            </span>
          ) : null}
        </div>
      ) : null}

      {running ? (
        <div className="space-y-2 px-5 py-5">
          <Spinner label="Reading the estate and reasoning about it" />
          <p className="text-center text-xs text-slate-600">
            {current?.evidence_used ?? 0} of {current?.evidence_budget ?? 0} evidence reads used
          </p>
        </div>
      ) : null}

      {current && current.status === "failed" ? (
        <div className="px-5 py-4">
          <p className="flex items-start gap-2 text-sm text-sev-critical">
            <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{current.error ?? "The investigation failed."}</span>
          </p>
        </div>
      ) : null}

      {current && current.status === "complete" && current.finding ? (
        <div className="space-y-4 px-5 py-4">
          {parseFinding(current.finding).map((section, i) => (
            <div key={`${section.label}-${i}`}>
              {section.label ? (
                <h3 className="label mb-1">{section.label}</h3>
              ) : null}
              <p
                className={`whitespace-pre-wrap text-sm leading-relaxed ${
                  section.label === "CONFIDENCE"
                    ? confidenceTone(section.body)
                    : section.label === "ROOT CAUSE"
                      ? "text-slate-100"
                      : "text-slate-400"
                }`}
              >
                {section.body}
              </p>
            </div>
          ))}

          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-surface-border pt-3 text-xs text-slate-600">
            <span className="inline-flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" />
              {served} evidence reads served
            </span>
            {current.duration_ms ? (
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {(current.duration_ms / 1000).toFixed(1)}s
              </span>
            ) : null}
            {current.model ? <span className="font-mono">{current.model}</span> : null}
            <span>requested by {current.requested_by}</span>
          </p>

          {discrepancy ? (
            <p className="flex items-start gap-2 rounded-lg border border-amber-700/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-400">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                The model reported {claimed} calls to Chetana tools but the gateway only handled{" "}
                {attempted}. The evidence chain below is the authoritative record — treat any claim
                that is not backed by a row there with suspicion.
              </span>
            </p>
          ) : null}
        </div>
      ) : null}

      {current && (current.evidence?.length ?? 0) > 0 ? (
        <div className="border-t border-surface-border">
          <button
            className="flex w-full items-center gap-2 px-5 py-2.5 text-left text-xs font-medium text-slate-400 hover:text-slate-200"
            onClick={() => setShowEvidence((v) => !v)}
          >
            {showEvidence ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
            <Database className="h-3.5 w-3.5" />
            Evidence chain — {current.evidence?.length} gateway calls
          </button>
          {showEvidence ? (
            <table className="w-full">
              <thead className="bg-surface-overlay/40">
                <tr>
                  <th className="th">Tool</th>
                  <th className="th">Arguments</th>
                  <th className="th">Result</th>
                  <th className="th">Took</th>
                </tr>
              </thead>
              <tbody>
                {(current.evidence ?? []).map((call) => (
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
          ) : null}
        </div>
      ) : null}

      {history.length > 1 ? (
        <div className="border-t border-surface-border px-5 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="label">Earlier runs</span>
            {history.slice(0, 6).map((item) => (
              <button
                key={item.id}
                onClick={() => void refresh(item.id)}
                className={`rounded-md border px-2 py-1 text-xs transition ${
                  item.id === current?.id
                    ? "border-accent/50 text-accent"
                    : "border-surface-border text-slate-500 hover:text-slate-300"
                }`}
              >
                {item.created_at ? new Date(item.created_at).toLocaleString() : item.id}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
