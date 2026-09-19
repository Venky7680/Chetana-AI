"use client";

import Link from "next/link";
import { ShieldQuestion } from "lucide-react";
import type { ApprovalRequest } from "@/lib/types";
import { TierBadge } from "./ui";

/**
 * Shown when the gateway parks an action. The point is that the operator sees
 * exactly why it did not run and what has to happen next — not a generic
 * "permission denied".
 */
export function ApprovalBanner({
  approval,
  message,
  onDismiss,
}: {
  approval: ApprovalRequest;
  message: string | null;
  onDismiss?: () => void;
}) {
  return (
    <div className="rounded-xl border border-amber-700/40 bg-amber-500/5 p-4">
      <div className="flex items-start gap-3">
        <ShieldQuestion className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 text-sm font-medium text-amber-300">
            Approval required <TierBadge tier={approval.tier} />
          </p>
          <p className="mt-1 text-xs text-amber-200/70">{message ?? approval.operation_id}</p>
          <p className="mt-2 text-xs text-slate-500">
            Requested by {approval.requested_by} ·{" "}
            {approval.approvals.length}/{approval.approvals_needed} approvals ·
            expires {new Date(approval.expires_at).toLocaleTimeString()}
          </p>
          <div className="mt-3 flex items-center gap-2">
            <Link href="/approvals" className="btn">
              Open approvals
            </Link>
            {onDismiss ? (
              <button className="btn" onClick={onDismiss}>
                Dismiss
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
