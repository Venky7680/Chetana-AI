"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { LayoutDashboard, Pencil, Plus, Save, Sparkles, Trash2, X } from "lucide-react";
import { DashboardCanvas } from "@/components/DashboardCanvas";
import { WidgetPicker, type PresetOption } from "@/components/WidgetPicker";
import {
  ChetanaChartWidget,
  PresetCountWidget,
  PresetTableWidget,
  clearPresetCache,
  type Analytics,
} from "@/components/widgets";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { ErrorState, ProblemBanner, Spinner } from "@/components/ui";
import { useApi, useSession } from "@/lib/session";
import { useAction } from "@/lib/useAction";
import {
  type Dashboard,
  type Widget,
  standardLayout,
  widgetsOf,
} from "@/lib/dashboard";

/**
 * Dashboards people build here, not in Keep.
 *
 * This page was a viewer for layouts assembled in Keep's own canvas, which
 * meant it was empty until somebody logged into Keep — the one thing this
 * console exists to avoid. It is now the builder: same storage (Keep's
 * `/dashboard` endpoints), same 24-column geometry, same field names, so a
 * layout saved here is a layout Keep understands.
 *
 * The empty state matters as much as the canvas. A blank grid is the problem
 * this page already had, so a tenant with nothing saved is offered a standard
 * layout to edit rather than a blank one to fill.
 */

interface DashboardsPayload {
  dashboards: Dashboard[];
  presets: PresetOption[];
  problems?: string[];
}

export default function DashboardsPage() {
  const { tenant } = useSession();
  const { data, error, loading, reload } = useApi<DashboardsPayload>("/dashboards");
  const { data: analytics } = useApi<Analytics>("/analytics");
  const action = useAction();

  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Widget[]>([]);
  const [draftName, setDraftName] = useState("");
  const [creating, setCreating] = useState(false);
  const [picking, setPicking] = useState(false);

  const dashboards = useMemo(() => data?.dashboards ?? [], [data]);
  const presets = data?.presets ?? [];
  const current = dashboards.find((d) => d.id === selected) ?? dashboards[0] ?? null;

  // Follow the server until the user picks, so a fresh save lands on its own
  // dashboard rather than bouncing back to the first one.
  useEffect(() => {
    if (!selected && dashboards.length > 0) setSelected(dashboards[0].id);
  }, [dashboards, selected]);

  const startEditing = useCallback((widgets: Widget[], name: string, isNew: boolean) => {
    setDraft(widgets);
    setDraftName(name);
    setCreating(isNew);
    setEditing(true);
  }, []);

  function cancel() {
    setEditing(false);
    setCreating(false);
    setDraft([]);
    action.reset();
  }

  async function save() {
    const name = draftName.trim();
    if (!name) return;
    const body = { dashboard_name: name, dashboard_config: { widgets: draft } };

    const saved = await action.run<Dashboard>(
      creating ? "/dashboards" : `/dashboards/${encodeURIComponent(current!.id)}`,
      { method: creating ? "POST" : "PUT", body, successMessage: "Saved" },
    );
    if (!saved) return; // parked for approval, or failed — the banner says which

    setEditing(false);
    setCreating(false);
    if (saved.id) setSelected(saved.id);
    clearPresetCache();
    reload();
  }

  async function remove() {
    if (!current) return;
    const done = await action.run(`/dashboards/${encodeURIComponent(current.id)}`, {
      method: "DELETE",
      successMessage: "Deleted",
    });
    if (done === null && action.parked) return;
    setSelected(null);
    reload();
  }

  const renderWidget = useCallback(
    (widget: Widget) => {
      if (widget.chetanaChart) {
        return <ChetanaChartWidget series={widget.chetanaChart.key} analytics={analytics ?? null} />;
      }
      if (widget.preset) {
        return widget.presetPanelType === "ALERT_COUNT_PANEL" ? (
          <PresetCountWidget widget={widget} />
        ) : (
          <PresetTableWidget widget={widget} />
        );
      }
      // A config Keep or an older console wrote, carrying a widget kind this
      // build does not know. Saying so beats an blank tile that looks broken.
      return (
        <p className="text-xs text-ink-muted">
          This widget was built with a kind this console does not render.
        </p>
      );
    },
    [analytics],
  );

  if (loading && !data) return <Spinner label="Loading dashboards" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  const widgets = editing ? draft : widgetsOf(current);

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-[-0.015em] text-ink">Dashboards</h1>
            {/* Editing is a mode, and a mode the user can leave with unsaved
                work in it. Saying so in the heading costs nothing and stops the
                "why is nothing saving" question. */}
            {editing ? (
              <span className="inline-flex items-center gap-1.5 rounded-md border border-accent/40 bg-accent/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-accent">
                <Pencil className="h-3 w-3" />
                Editing
              </span>
            ) : null}
          </div>
          <p className="mt-1.5 max-w-2xl text-sm text-ink-muted">
            {editing
              ? "Drag by the handle, resize from the bottom-right corner. Nothing is saved until you press Save."
              : "Built and saved here. Nobody has to open Keep to assemble one."}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {editing ? (
            <>
              <button className="btn" onClick={() => setPicking(true)}>
                <Plus className="h-3.5 w-3.5" />
                Add widget
              </button>
              <button className="btn-quiet" onClick={cancel}>
                <X className="h-3.5 w-3.5" />
                Cancel
              </button>
              <button className="btn-primary" onClick={save} disabled={action.busy || !draftName.trim()}>
                <Save className="h-3.5 w-3.5" />
                {action.busy ? "Saving" : "Save"}
              </button>
            </>
          ) : (
            <>
              <button
                // Always secondary. When there is nothing saved the empty
                // state below carries the primary action, and two filled
                // buttons on one screen means neither is the obvious one.
                className="btn"
                onClick={() => startEditing([], `${tenant?.name ?? "New"} dashboard`, true)}
              >
                <Plus className="h-3.5 w-3.5" />
                New dashboard
              </button>
              {current ? (
                <>
                  <button
                    className="btn"
                    onClick={() => startEditing(widgetsOf(current), current.dashboard_name, false)}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                    Edit
                  </button>
                  <button className="btn-danger" onClick={remove} disabled={action.busy}>
                    <Trash2 className="h-3.5 w-3.5" />
                    Delete
                  </button>
                </>
              ) : null}
            </>
          )}
        </div>
      </header>

      <ProblemBanner problems={data?.problems} />
      {action.parked ? (
        <ApprovalBanner approval={action.parked} message={action.message} onDismiss={action.reset} />
      ) : null}
      {action.error ? <ErrorState message={action.error} /> : null}

      {/* Tabs. Hidden while editing, because switching mid-edit would throw the draft away. */}
      {!editing && dashboards.length > 0 ? (
        <nav
          aria-label="Saved dashboards"
          className="flex flex-wrap items-center gap-6 border-b border-surface-border"
        >
          {dashboards.map((dashboard) => {
            const active = dashboard.id === current?.id;
            return (
              <button
                key={dashboard.id}
                aria-current={active ? "page" : undefined}
                onClick={() => setSelected(dashboard.id)}
                className={`-mb-px border-b-2 pb-2.5 text-[13px] font-medium transition ${
                  active
                    ? "border-accent text-ink"
                    : "border-transparent text-ink-muted hover:border-surface-firm hover:text-ink-2"
                }`}
              >
                {dashboard.dashboard_name}
                <span className="ml-2 text-[11px] font-normal tabular-nums text-ink-faint">
                  {widgetsOf(dashboard).length}
                </span>
              </button>
            );
          })}
        </nav>
      ) : null}

      {editing ? (
        <label className="block max-w-sm">
          <span className="label">Dashboard name</span>
          <input
            className="input mt-1"
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            maxLength={120}
            autoFocus
          />
        </label>
      ) : null}

      {/* Empty states. The one that matters is the first: a brand-new tenant
          should never be shown a blank grid and left to guess. */}
      {!editing && dashboards.length === 0 ? (
        <div className="card flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent/10">
            <LayoutDashboard className="h-6 w-6 text-accent" />
          </span>
          <h2 className="mt-4 text-base font-semibold tracking-[-0.01em] text-ink">
            No dashboards yet
          </h2>
          <p className="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-ink-muted">
            Start from the standard layout — noise reduction, alert volume, the noisiest services
            and the investigation engine, already arranged — then move things around and save.
          </p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <button
              className="btn-primary"
              onClick={() =>
                startEditing(standardLayout(), `${tenant?.name ?? "Client"} overview`, true)
              }
            >
              <Sparkles className="h-3.5 w-3.5" />
              Start from the standard layout
            </button>
            <button className="btn" onClick={() => startEditing([], "New dashboard", true)}>
              Start empty
            </button>
          </div>
        </div>
      ) : editing && draft.length === 0 ? (
        <button
          onClick={() => setPicking(true)}
          className="flex w-full flex-col items-center gap-1.5 rounded-xl border border-dashed border-surface-firm py-16 text-ink-muted transition hover:border-accent hover:bg-accent/5 hover:text-ink-2"
        >
          <Plus className="h-5 w-5" />
          <span className="text-sm">Add the first widget</span>
        </button>
      ) : (
        <DashboardCanvas
          widgets={widgets}
          editing={editing}
          onChange={setDraft}
          onRemove={(id) => setDraft((prev) => prev.filter((w) => w.i !== id))}
          renderWidget={renderWidget}
        />
      )}

      {editing ? (
        <p className="text-xs text-ink-faint">
          With a drag handle focused, the arrow keys move a widget and shift with the arrow keys
          resizes it.
        </p>
      ) : null}

      {picking ? (
        <WidgetPicker
          presets={presets}
          existing={draft}
          onAdd={(widget) => setDraft((prev) => [...prev, widget])}
          onClose={() => setPicking(false)}
        />
      ) : null}
    </div>
  );
}
