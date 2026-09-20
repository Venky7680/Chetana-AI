"use client";

import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle, RotateCcw } from "lucide-react";

/**
 * Segment error boundary for the console.
 *
 * Without this, one unhandled render exception unmounts the whole app and the
 * operator sees a black screen with "a client-side exception has occurred" —
 * which says nothing about what broke, on a tool whose entire job is telling
 * people what broke. Now the sidebar stays, the page reports the actual error,
 * and the rest of the console is still navigable.
 */
export default function ConsoleError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Keeps the full stack in the browser console for anyone debugging.
    console.error("[chetana] page render failed:", error);
  }, [error]);

  return (
    <div className="mx-auto max-w-2xl py-10">
      <div className="rounded-xl border border-sev-critical/30 bg-sev-critical/5 p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-sev-critical" />
          <div className="min-w-0 flex-1">
            <h1 className="text-base font-semibold text-slate-100">This page failed to render</h1>
            <p className="mt-1 text-sm text-slate-400">
              The console is still running — the sidebar works and other pages are unaffected.
            </p>

            <pre className="mt-4 max-h-48 overflow-auto rounded-lg border border-surface-border bg-surface-base p-3 font-mono text-xs text-slate-400">
              {error.message || "No message was attached to the error."}
            </pre>
            {error.digest ? (
              <p className="mt-2 font-mono text-[11px] text-slate-600">digest {error.digest}</p>
            ) : null}

            <div className="mt-5 flex flex-wrap gap-2">
              <button className="btn-primary" onClick={reset}>
                <RotateCcw className="h-3.5 w-3.5" />
                Try again
              </button>
              <Link href="/overview" className="btn">
                Back to overview
              </Link>
            </div>

            <p className="mt-4 text-xs text-slate-600">
              A shape mismatch between Keep and the console usually causes this — the browser
              console above has the stack.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
