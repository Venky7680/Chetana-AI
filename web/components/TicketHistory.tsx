"use client";

import { useRef, useState } from "react";
import { Check, FileUp, Loader2, ShieldCheck, Trash2, Upload } from "lucide-react";
import { api, upload as uploadFile } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import { ErrorState, RelativeTime } from "@/components/ui";

/**
 * Dropping ticket exports in, and seeing what happened to them.
 *
 * The corpus this builds is what the investigation engine searches for
 * precedent, and what the runbook candidates below are derived from. Until now
 * it could only be produced by a command-line script against a read-only mount,
 * which meant the person holding the export was never the person who could load
 * it.
 *
 * Two things are shown rather than asserted, because both are claims a client
 * will eventually ask you to back up. What redaction actually caught is
 * reported per upload — "we strip personal data" is worth less than a count of
 * what was stripped. And the corpus states whether it is this client's own
 * history or the shared demo corpus, because one is evidence and the other is
 * an illustration.
 */

interface UploadRecord {
  file: string;
  rows: number;
  skipped?: number;
  redacted?: Record<string, number>;
  by?: string;
  at?: string;
}

interface Summary {
  owned: boolean;
  corpus: {
    name?: string;
    kind?: string;
    tickets?: number;
    patterns_loaded?: number;
    window?: string;
    caveat?: string;
  } | null;
  uploads: UploadRecord[];
  counts: Record<string, number>;
}

const REDACTION_LABEL: Record<string, string> = {
  name: "names",
  email: "email addresses",
  phone: "phone numbers",
  ticket: "ticket references",
  ip: "IP addresses",
};

function redactionSummary(counts: Record<string, number> | undefined): string {
  const parts = Object.entries(counts ?? {})
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([key, n]) => `${n.toLocaleString()} ${REDACTION_LABEL[key] ?? key}`);
  return parts.length ? `Removed ${parts.join(", ")}` : "Nothing matched the redaction patterns";
}

export function TicketHistory({ onChanged }: { onChanged: () => void }) {
  const { tenant } = useSession();
  const { data, reload } = useApi<Summary>("/precedents");
  const input = useRef<HTMLInputElement>(null);

  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<UploadRecord | null>(null);

  async function ingest(files: FileList | File[]) {
    const list = Array.from(files).filter((f) => f.name.toLowerCase().endsWith(".csv"));
    if (list.length === 0) {
      setError("Only .csv exports can be read. Export the ticket list as CSV first.");
      return;
    }
    setError(null);
    setDone(null);

    // Sequential rather than parallel: each upload merges into the corpus the
    // previous one produced, and two concurrent merges would race to write it.
    for (const file of list) {
      setBusy(file.name);
      try {
        const result = await uploadFile<{ ingested: UploadRecord }>("/precedents", file);
        setDone(result.ingested);
      } catch (err) {
        setError(err instanceof Error ? err.message : `Could not read ${file.name}`);
        break;
      }
    }
    setBusy(null);
    reload();
    onChanged();
  }

  async function clear() {
    setError(null);
    try {
      await api("/precedents", { method: "DELETE" });
      setDone(null);
      reload();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the ticket history");
    }
  }

  const corpus = data?.corpus ?? null;
  const owned = data?.owned ?? false;
  const uploads = data?.uploads ?? [];

  return (
    <section className="card-pad space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Ticket history</h2>
          <p className="mt-0.5 max-w-2xl text-xs text-slate-600">
            Drop closed-ticket exports for {tenant?.name ?? "this client"}. Each one adds to what
            is already here — counts grow and new fix patterns appear, so several years of
            exports are better than one.
          </p>
        </div>
        {owned ? (
          <button className="btn-danger" onClick={clear} disabled={Boolean(busy)}>
            <Trash2 className="h-3.5 w-3.5" />
            Remove all
          </button>
        ) : null}
      </div>

      {/* The dropzone is also a button and also a file input, because a
          drop-only target is unusable from a keyboard. */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files?.length) ingest(e.dataTransfer.files);
        }}
        className={`rounded-xl border border-dashed transition ${
          dragging ? "border-accent bg-accent/5" : "border-surface-border"
        }`}
      >
        <button
          type="button"
          onClick={() => input.current?.click()}
          disabled={Boolean(busy)}
          className="flex w-full flex-col items-center gap-2 px-4 py-9 text-center disabled:opacity-60"
        >
          {busy ? (
            <>
              <Loader2 className="h-5 w-5 animate-spin text-accent" />
              <span className="text-sm text-slate-300">Reading {busy}</span>
            </>
          ) : (
            <>
              <FileUp className={`h-5 w-5 ${dragging ? "text-accent" : "text-slate-600"}`} />
              <span className="text-sm text-slate-300">
                Drop CSV exports here, or click to choose
              </span>
              <span className="text-xs text-slate-600">
                Needs a short description and resolution notes per row. Up to 40MB each.
              </span>
            </>
          )}
        </button>
        <input
          ref={input}
          id="ticket-history-file"
          type="file"
          accept=".csv,text/csv"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) ingest(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {error ? <ErrorState message={error} /> : null}

      {done ? (
        <div className="rounded-lg border border-emerald-700/40 bg-emerald-500/5 px-4 py-3">
          <p className="flex items-center gap-2 text-sm text-emerald-400">
            <Check className="h-4 w-4" />
            Read {done.rows.toLocaleString()} tickets from {done.file}
          </p>
          <p className="mt-1 flex items-start gap-2 text-xs text-slate-500">
            <ShieldCheck className="mt-0.5 h-3 w-3 shrink-0" />
            <span>
              {redactionSummary(done.redacted)}. The file itself was not kept — only the
              patterns derived from it.
            </span>
          </p>
        </div>
      ) : null}

      {corpus ? (
        <div
          className={`rounded-lg border px-4 py-3 ${
            owned ? "border-surface-border bg-surface-base" : "border-sev-warning/30 bg-sev-warning/5"
          }`}
        >
          <h3 className="flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-300">
            {owned ? "This client's history" : "Shared demo corpus"}
            <span
              className={`chip ${
                corpus.kind === "historical"
                  ? "border-emerald-700/40 text-emerald-400"
                  : "border-sev-warning/40 text-sev-warning"
              }`}
            >
              {corpus.kind ?? "unknown"}
            </span>
          </h3>
          <p className="mt-1 text-xs text-slate-400">
            {corpus.patterns_loaded?.toLocaleString()} patterns
            {corpus.tickets ? ` from ${corpus.tickets.toLocaleString()} tickets` : ""}
            {corpus.window ? ` · ${corpus.window}` : ""}
          </p>
          {!owned ? (
            <p className="mt-1.5 max-w-2xl text-xs text-sev-warning/90">
              Nothing has been uploaded for this client, so investigations fall back to the
              bundled demo corpus. Its patterns are invented, and every search result says so.
              Upload a real export to replace it.
            </p>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-slate-600">
          Nothing loaded. Investigations for this client reason only from live evidence — they
          cannot cite how a symptom was resolved before.
        </p>
      )}

      {uploads.length > 0 ? (
        <div>
          <h3 className="label mb-2">Ingested</h3>
          <ul className="space-y-1.5">
            {uploads.map((record, index) => (
              <li
                key={`${record.file}-${index}`}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs"
              >
                <Upload className="h-3 w-3 shrink-0 text-slate-600" />
                <span className="text-slate-300">{record.file}</span>
                <span className="tabular-nums text-slate-500">
                  {record.rows.toLocaleString()} tickets
                </span>
                {record.skipped ? (
                  <span className="text-slate-600">{record.skipped} rows unusable</span>
                ) : null}
                <span className="text-slate-600">{redactionSummary(record.redacted)}</span>
                {record.by ? <span className="text-slate-600">· {record.by}</span> : null}
                {record.at ? <RelativeTime value={record.at} /> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
