"use client";

import { useState } from "react";
import { CalendarClock, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import type { MaintenanceRule } from "@/lib/types";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { EmptyState, ErrorState, GatedAction, Spinner } from "@/components/ui";

function defaultStart() {
  // datetime-local wants local time with no zone suffix.
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60000);
  return now.toISOString().slice(0, 16);
}

export default function MaintenancePage() {
  const { can } = useSession();
  const { data, error, loading, reload } = useApi<MaintenanceRule[]>("/maintenance");
  const action = useAction();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    cel_query: "",
    start_time: defaultStart(),
    hours: 2,
  });

  const windows = Array.isArray(data) ? data : [];

  async function create() {
    await action.run("/maintenance", {
      body: {
        name: form.name,
        cel_query: form.cel_query,
        start_time: new Date(form.start_time).toISOString(),
        duration_seconds: Math.round(Number(form.hours) * 3600),
        enabled: true,
        suppress: true,
      },
      successMessage: "Maintenance window opened",
    });
    setShowForm(false);
    reload();
  }

  async function close(id: string) {
    await api(`/maintenance/${id}`, { method: "DELETE" });
    reload();
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Maintenance windows</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Suppress alerts matching a CEL predicate for a fixed period, so a planned change does
            not page anyone. Opening one is tier R1 — it expires on its own, so it is reversible by
            construction.
          </p>
        </div>
        <GatedAction
          capability={can("maintenance.create")}
          busy={action.busy}
          onClick={() => setShowForm((v) => !v)}
        >
          <Plus className="h-3.5 w-3.5" />
          New window
        </GatedAction>
      </header>

      {action.parked ? (
        <ApprovalBanner approval={action.parked} message={action.message} onDismiss={action.reset} />
      ) : null}
      {action.error ? <ErrorState message={action.error} /> : null}
      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      {showForm ? (
        <section className="card-pad space-y-3">
          <h2 className="text-sm font-semibold text-slate-200">Open a maintenance window</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block sm:col-span-1">
              <span className="label mb-1.5 block">Name</span>
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Ledger patching"
              />
            </label>
            <label className="block">
              <span className="label mb-1.5 block">Starts</span>
              <input
                className="input"
                type="datetime-local"
                value={form.start_time}
                onChange={(e) => setForm({ ...form, start_time: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="label mb-1.5 block">Duration (hours)</span>
              <input
                className="input"
                type="number"
                min={0.5}
                step={0.5}
                value={form.hours}
                onChange={(e) => setForm({ ...form, hours: Number(e.target.value) })}
              />
            </label>
          </div>
          <label className="block">
            <span className="label mb-1.5 block">Suppress alerts matching</span>
            <input
              className="input font-mono text-xs"
              value={form.cel_query}
              onChange={(e) => setForm({ ...form, cel_query: e.target.value })}
              placeholder='service == "ledger-worker"'
            />
          </label>
          <div className="flex gap-2">
            <GatedAction
              capability={can("maintenance.create")}
              busy={action.busy}
              onClick={create}
            >
              Open window
            </GatedAction>
            <button className="btn" onClick={() => setShowForm(false)}>
              Cancel
            </button>
          </div>
        </section>
      ) : null}

      <div className="card">
        {loading && !data ? (
          <Spinner />
        ) : windows.length === 0 ? (
          <EmptyState
            title="No maintenance windows"
            hint="Nothing is being suppressed — every alert reaches the console."
          />
        ) : (
          <table className="w-full">
            <thead className="bg-surface-overlay/40">
              <tr>
                <th className="th">Window</th>
                <th className="th">Matches</th>
                <th className="th">Starts</th>
                <th className="th">Ends</th>
                <th className="th">State</th>
                <th className="th" />
              </tr>
            </thead>
            <tbody>
              {windows.map((window) => (
                <tr key={window.id} className="row">
                  <td className="td">
                    <p className="font-medium text-slate-200">{window.name}</p>
                    {window.created_by ? (
                      <p className="mt-0.5 text-xs text-slate-600">{window.created_by}</p>
                    ) : null}
                  </td>
                  <td className="td max-w-xs break-all font-mono text-xs text-slate-400">
                    {window.cel_query ?? "—"}
                  </td>
                  <td className="td whitespace-nowrap text-xs text-slate-400">
                    {window.start_time ? new Date(window.start_time).toLocaleString() : "—"}
                  </td>
                  <td className="td whitespace-nowrap text-xs text-slate-400">
                    {window.end_time ? new Date(window.end_time).toLocaleString() : "—"}
                  </td>
                  <td className="td">
                    <span
                      className={`inline-flex items-center gap-1.5 text-xs ${
                        window.enabled ? "text-amber-400" : "text-slate-500"
                      }`}
                    >
                      <CalendarClock className="h-3.5 w-3.5" />
                      {window.enabled ? "suppressing" : "inactive"}
                    </span>
                  </td>
                  <td className="td">
                    <GatedAction
                      capability={can("maintenance.delete")}
                      variant="plain"
                      onClick={() => close(window.id)}
                    >
                      Close
                    </GatedAction>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
