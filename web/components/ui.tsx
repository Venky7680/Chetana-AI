"use client";

import { AlertTriangle, Inbox, Loader2, Lock, ShieldQuestion } from "lucide-react";
import type { Capability } from "@/lib/types";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "border-sev-critical/40 bg-sev-critical/10 text-sev-critical",
  high: "border-sev-high/40 bg-sev-high/10 text-sev-high",
  warning: "border-sev-warning/40 bg-sev-warning/10 text-sev-warning",
  medium: "border-sev-warning/40 bg-sev-warning/10 text-sev-warning",
  low: "border-sev-low/40 bg-sev-low/10 text-sev-low",
  info: "border-sev-info/40 bg-sev-info/10 text-sev-info",
};

/**
 * Severity always ships with its name.
 *
 * Five severity hues cannot pass a colour-separation gate — high and warning
 * measure ΔE 8.7 apart, and no repalette fixes that without making warning stop
 * looking like warning. So the word carries the meaning and the colour only
 * reinforces it. Nothing in this console is severity-coloured without being
 * severity-labelled.
 */
export function SeverityBadge({ severity }: { severity: string }) {
  const style =
    SEVERITY_STYLES[severity] ?? "border-surface-border bg-surface-overlay text-ink-muted";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 pl-1.5 text-[11px] font-semibold uppercase tracking-wide ${style}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {severity}
    </span>
  );
}

const STATUS_STYLES: Record<string, string> = {
  firing: "text-sev-critical",
  alerting: "text-sev-critical",
  open: "text-sev-critical",
  acknowledged: "text-sev-warning",
  in_progress: "text-sev-warning",
  resolved: "text-good",
  suppressed: "text-ink-muted",
};

export function StatusDot({ status }: { status: string }) {
  const tone = STATUS_STYLES[status] ?? "text-ink-muted";
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${tone}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

const TIER_COPY: Record<number, { label: string; hint: string; className: string }> = {
  0: { label: "R0", hint: "Read only", className: "border-surface-firm text-ink-muted" },
  1: {
    label: "R1",
    hint: "Auto-reversible — runs without approval",
    className: "border-good/40 bg-good/10 text-good",
  },
  2: {
    label: "R2",
    hint: "Reversible with effort — one approval",
    className: "border-sev-warning/40 bg-sev-warning/10 text-sev-warning",
  },
  3: {
    label: "R3",
    hint: "Irreversible — two approvals",
    className: "border-sev-critical/40 bg-sev-critical/10 text-sev-critical",
  },
};

export function TierBadge({ tier }: { tier: number }) {
  const meta = TIER_COPY[tier] ?? TIER_COPY[0];
  return (
    <span
      title={meta.hint}
      className={`inline-flex rounded border px-1.5 py-0.5 font-mono text-[11px] font-semibold ${meta.className}`}
    >
      {meta.label}
    </span>
  );
}

export function StatCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "warn" | "critical" | "good";
}) {
  const toneClass = {
    default: "text-ink",
    warn: "text-sev-warning",
    critical: "text-sev-critical",
    good: "text-emerald-400",
  }[tone];

  return (
    <div className="card-pad">
      <p className="label">{label}</p>
      <p className={`mt-2 text-[26px] font-semibold leading-none tracking-[-0.02em] tabular-nums ${toneClass}`}>
        {value}
      </p>
      {hint ? <p className="mt-1 text-xs text-ink-muted">{hint}</p> : null}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-10 text-sm text-ink-muted">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}…
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
      <Inbox className="h-6 w-6 text-ink-faint" />
      <p className="text-sm font-medium text-ink-2">{title}</p>
      {hint ? <p className="max-w-sm text-xs text-ink-muted">{hint}</p> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-sev-critical/30 bg-sev-critical/5 p-5">
      <div className="flex items-center gap-2 text-sm font-medium text-sev-critical">
        <AlertTriangle className="h-4 w-4" />
        {message}
      </div>
      {onRetry ? (
        <button className="btn" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

/**
 * Wraps an action button with what the BFF says about it *before* the click:
 * live, needs approval, or not permitted. The capability comes from the server,
 * so the UI can never claim more authority than the gateway grants.
 */
export function GatedAction({
  capability,
  onClick,
  busy,
  children,
  variant = "primary",
}: {
  capability: Capability | undefined;
  onClick: () => void;
  busy?: boolean;
  children: React.ReactNode;
  variant?: "primary" | "danger" | "plain";
}) {
  const decision = capability?.decision;
  const disabled = !capability || decision === "denied" || busy;

  const className =
    variant === "danger" ? "btn-danger" : variant === "plain" ? "btn" : "btn-primary";

  const icon = busy ? (
    <Loader2 className="h-3.5 w-3.5 animate-spin" />
  ) : decision === "denied" ? (
    <Lock className="h-3.5 w-3.5" />
  ) : decision === "approval_required" ? (
    <ShieldQuestion className="h-3.5 w-3.5" />
  ) : null;

  return (
    <button
      className={className}
      onClick={onClick}
      disabled={disabled}
      title={capability?.reason ?? "Unavailable"}
    >
      {icon}
      {children}
      {capability ? <TierBadge tier={capability.tier} /> : null}
    </button>
  );
}

/**
 * Some pages fan out to two or three Keep calls. When one fails, that section
 * is not "empty" — it is broken, and saying so is the whole point. Rendering
 * an empty state for a failed call is how you end up debugging the wrong thing.
 */
export function ProblemBanner({ problems }: { problems?: string[] }) {
  if (!problems || problems.length === 0) return null;
  return (
    <div className="rounded-xl border border-sev-critical/30 bg-sev-critical/5 p-4">
      <p className="flex items-center gap-2 text-sm font-medium text-sev-critical">
        <AlertTriangle className="h-4 w-4" />
        Keep did not answer for part of this page
      </p>
      <ul className="mt-2 space-y-0.5">
        {problems.map((problem) => (
          <li key={problem} className="break-all font-mono text-xs text-ink-2">
            {problem}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-ink-muted">
        These calls failed — which is not the same as the section being empty.
      </p>
    </div>
  );
}

export function RelativeTime({ value }: { value: string | null }) {
  if (!value) return <span className="text-ink-faint">—</span>;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return <span className="text-ink-faint">—</span>;

  const diffMs = Date.now() - date.getTime();
  const minutes = Math.round(diffMs / 60000);
  let text: string;
  if (minutes < 1) text = "just now";
  else if (minutes < 60) text = `${minutes}m ago`;
  else if (minutes < 60 * 24) text = `${Math.round(minutes / 60)}h ago`;
  else text = `${Math.round(minutes / 1440)}d ago`;

  return (
    <span title={date.toLocaleString()} className="whitespace-nowrap text-ink-muted">
      {text}
    </span>
  );
}
