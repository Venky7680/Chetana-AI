"use client";

import { useMemo, useState } from "react";
import { Info, ShieldCheck, Wrench } from "lucide-react";
import { useApi } from "@/lib/session";
import { TicketHistory } from "@/components/TicketHistory";
import { ErrorState, Spinner, StatCard, TierBadge } from "@/components/ui";

/**
 * What is worth automating, and what it would cost to get wrong.
 *
 * Auto-remediation usually gets built the other way round: pick the tool, wire
 * it to the loudest alert, discover afterwards which actions could not be
 * undone. This page is the other order — the repeatable fixes that actually
 * recur in closed tickets, each with the one question that decides whether a
 * machine may run it unattended: what happens if it was the wrong call.
 *
 * Nothing here executes. It is a review surface, and every tier on it is a
 * proposal for a human to confirm.
 */

interface Candidate {
  tickets: number;
  tier: string;
  rationale: string;
  ci_class: string;
  owning_team: string;
  resolution: string;
}

const TIER_NUMBER: Record<string, number> = { R0: 0, R1: 1, R2: 2, R3: 3 };

const TIER_MEANING: Record<string, string> = {
  R1: "Runs without an approval. The action reverses itself, or removes only data that regenerates.",
  R2: "Runs behind an approval. Undoing it takes effort, costs money, or someone will notice.",
  R3: "Never unattended. Cannot be undone.",
};

export default function RunbooksPage() {
  const { data, error, loading, reload } = useApi<{
    items: Candidate[];
    by_tier: Record<string, { runbooks: number; tickets: number }>;
  }>("/runbooks/candidates");
  const [tier, setTier] = useState<string>("all");

  const items = useMemo(() => data?.items ?? [], [data]);
  const shown = tier === "all" ? items : items.filter((i) => i.tier === tier);
  const tiers = Object.keys(data?.by_tier ?? {}).sort();
  const totalTickets = items.reduce((sum, i) => sum + i.tickets, 0);

  if (loading && !data) return <Spinner label="Reading candidates" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  if (items.length === 0) {
    return (
      <div className="space-y-5">
        <header>
          <h1 className="text-xl font-semibold text-slate-100">Runbook candidates</h1>
        </header>
        <p className="max-w-3xl text-sm text-slate-500">
          Nothing to propose yet. These come from closed tickets — drop an export below and the
          repeatable fixes fall out of it. Guessing at what an estate repeatedly does is exactly
          the wrong way to choose what to automate.
        </p>
        <TicketHistory onChanged={reload} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Runbook candidates</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Fixes that recur often enough in closed tickets to be worth automating, each with a
          proposed autonomy tier. Nothing here is wired to anything — it is the review step
          before auto-remediation gets built.
        </p>
      </header>

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Candidates" value={items.length} hint="distinct repeatable fixes" />
        <StatCard
          label="Tickets covered"
          value={totalTickets.toLocaleString()}
          hint="in the source export"
        />
        {tiers.map((t) => (
          <StatCard
            key={t}
            label={t === "R1" ? "Unattended" : t === "R2" ? "Needs approval" : t}
            value={data?.by_tier[t]?.runbooks ?? 0}
            hint={`${data?.by_tier[t]?.tickets ?? 0} tickets`}
            tone={t === "R1" ? "good" : "default"}
          />
        ))}
      </section>

      <p className="glass flex items-start gap-2 rounded-xl px-4 py-3 text-xs text-ink-muted">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          The tier is set by how hard the action is to undo, never by how urgent the alert was.
          A password reset is not tier 1 just because it is quick — the old secret is gone. Two
          candidates were re-tiered for exactly that reason while this list was built.
        </span>
      </p>

      <div className="flex flex-wrap gap-1.5">
        {["all", ...tiers].map((key) => (
          <button
            key={key}
            onClick={() => setTier(key)}
            className={`rounded-lg border px-3 py-1.5 text-xs transition ${
              tier === key
                ? "border-accent bg-accent/10 text-accent"
                : "border-surface-border text-slate-400 hover:border-slate-500"
            }`}
          >
            {key === "all" ? `All ${items.length}` : `${key} · ${data?.by_tier[key]?.runbooks ?? 0}`}
          </button>
        ))}
      </div>

      <div className="card overflow-hidden">
        <table className="w-full">
          <thead className="bg-surface-overlay/40">
            <tr>
              <th className="th">Fix</th>
              <th className="th">Component</th>
              <th className="th">Usually handled by</th>
              <th className="th text-right">Seen</th>
              <th className="th">Tier</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((item, index) => (
              <tr key={`${item.ci_class}-${index}`} className="row align-top">
                <td className="td max-w-xl">
                  <p className="text-slate-200">{item.resolution}</p>
                  <p className="mt-0.5 text-xs text-slate-600">{item.rationale}</p>
                </td>
                <td className="td font-mono text-xs text-slate-400">{item.ci_class}</td>
                <td className="td text-slate-400">{item.owning_team}</td>
                <td className="td tabular-nums text-right text-slate-300">{item.tickets}</td>
                <td className="td">
                  <span title={TIER_MEANING[item.tier] ?? item.tier}>
                    <TierBadge tier={TIER_NUMBER[item.tier] ?? 2} />
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <TicketHistory onChanged={reload} />

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="card-pad">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Wrench className="h-4 w-4 text-accent" />
            What this list is not
          </h2>
          <p className="mt-1.5 text-xs text-slate-500">
            It covers only the fixes that repeat. Most of what a service desk does is
            one-of-a-kind or physical — a cable, a laptop, a conversation — and no amount of
            automation touches it. Treat the ticket coverage above as the ceiling on what
            auto-remediation can honestly claim, not as a target.
          </p>
        </div>
        <div className="card-pad">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <ShieldCheck className="h-4 w-4 text-accent" />
            Before any of it runs
          </h2>
          <p className="mt-1.5 text-xs text-slate-500">
            Each one becomes a workflow, gated by the same tiers as everything else: R1 executes,
            R2 parks for approval. The tier shown here is a proposal from the wording of the
            resolution — confirm it against what the action actually does in your estate before
            it is built.
          </p>
        </div>
      </div>
    </div>
  );
}
