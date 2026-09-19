"use client";

import { useState } from "react";
import { ArrowRight, Plus, X } from "lucide-react";
import { useAction } from "@/lib/useAction";
import { ApprovalBanner } from "@/components/ApprovalBanner";
import { ErrorState } from "@/components/ui";
import type { TopologyService } from "@/lib/types";

/**
 * Declaring topology by hand.
 *
 * Keep normally discovers a service map from a provider that exposes one.
 * Plenty of estates have no such provider, and an MSP usually knows the graph
 * anyway — from the CMDB, or from having built the thing. The BFF has been able
 * to write services and dependencies for a while; this is the part that was
 * missing, which is why the page looked read-only.
 *
 * Topology is not decoration. The investigation engine walks it to reach past
 * the service that is shouting to the one actually at fault, so a missing edge
 * shows up later as a root cause analysis that blames the victim.
 */

const PROTOCOLS = ["HTTP", "gRPC", "SQL", "AMQP", "Kafka", "TCP", "unknown"];

export function TopologyEditor({
  services,
  onChanged,
}: {
  services: TopologyService[];
  onChanged: () => void;
}) {
  const action = useAction();
  const [open, setOpen] = useState<"service" | "dependency" | null>(null);

  // service form
  const [name, setName] = useState("");
  const [display, setDisplay] = useState("");
  const [environment, setEnvironment] = useState("production");
  const [description, setDescription] = useState("");
  const [team, setTeam] = useState("");

  // dependency form
  const [caller, setCaller] = useState("");
  const [callee, setCallee] = useState("");
  const [protocol, setProtocol] = useState("HTTP");

  function close() {
    setOpen(null);
    action.reset();
  }

  async function addService() {
    const service = name.trim();
    if (!service) return;
    const done = await action.run("/topology/services", {
      body: {
        service,
        display_name: display.trim() || service,
        environment: environment.trim() || "unknown",
        description: description.trim() || null,
        team: team.trim() || null,
      },
      successMessage: "Service added",
    });
    if (!done) return;
    setName("");
    setDisplay("");
    setDescription("");
    setTeam("");
    setOpen(null);
    onChanged();
  }

  async function addDependency() {
    if (!caller || !callee || caller === callee) return;
    const done = await action.run("/topology/dependencies", {
      body: {
        service_id: Number(caller),
        depends_on_service_id: Number(callee),
        protocol,
      },
      successMessage: "Dependency added",
    });
    if (!done) return;
    setCaller("");
    setCallee("");
    setOpen(null);
    onChanged();
  }

  const callerName = services.find((s) => String(s.id) === caller);
  const calleeName = services.find((s) => String(s.id) === callee);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button
          className={open === "service" ? "btn-primary" : "btn"}
          onClick={() => (open === "service" ? close() : setOpen("service"))}
        >
          <Plus className="h-3.5 w-3.5" />
          Add service
        </button>
        <button
          className={open === "dependency" ? "btn-primary" : "btn"}
          onClick={() => (open === "dependency" ? close() : setOpen("dependency"))}
          disabled={services.length < 2}
          title={
            services.length < 2
              ? "Two services are needed before one can depend on the other"
              : undefined
          }
        >
          <Plus className="h-3.5 w-3.5" />
          Add dependency
        </button>
      </div>

      {open === "service" ? (
        <form
          className="card-pad space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            addService();
          }}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-200">New service</h3>
              <p className="mt-0.5 text-xs text-slate-600">
                The name must match what alerts carry in their <code className="font-mono">service</code>{" "}
                field, or nothing will correlate to it.
              </p>
            </div>
            <button type="button" onClick={close} aria-label="Close" className="text-slate-600 hover:text-slate-300">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="label">Service name</span>
              <input
                className="input mt-1 font-mono text-xs"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="payments-api"
                maxLength={255}
                autoFocus
              />
            </label>
            <label className="block">
              <span className="label">Display name</span>
              <input
                className="input mt-1"
                value={display}
                onChange={(e) => setDisplay(e.target.value)}
                placeholder={name || "Payments API"}
                maxLength={255}
              />
            </label>
            <label className="block">
              <span className="label">Environment</span>
              <input
                className="input mt-1"
                value={environment}
                onChange={(e) => setEnvironment(e.target.value)}
                placeholder="production"
              />
            </label>
            <label className="block">
              <span className="label">Owning team</span>
              <input
                className="input mt-1"
                value={team}
                onChange={(e) => setTeam(e.target.value)}
                placeholder="Optional"
              />
            </label>
          </div>

          <label className="block">
            <span className="label">Description</span>
            <input
              className="input mt-1"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What it does, and what its failure looks like"
            />
          </label>

          <div className="flex justify-end gap-2">
            <button type="button" className="btn" onClick={close}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={action.busy || !name.trim()}>
              {action.busy ? "Adding" : "Add service"}
            </button>
          </div>
        </form>
      ) : null}

      {open === "dependency" ? (
        <form
          className="card-pad space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            addDependency();
          }}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-200">New dependency</h3>
              <p className="mt-0.5 text-xs text-slate-600">
                Direction matters and is easy to invert. Read it as the caller depending on the
                callee — get it backwards and an investigation blames the victim.
              </p>
            </div>
            <button type="button" onClick={close} aria-label="Close" className="text-slate-600 hover:text-slate-300">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="grid items-end gap-3 sm:grid-cols-[1fr_auto_1fr_auto]">
            <label className="block">
              <span className="label">This service…</span>
              <select className="input mt-1" value={caller} onChange={(e) => setCaller(e.target.value)}>
                <option value="">Choose the caller</option>
                {services.map((s) => (
                  <option key={String(s.id)} value={String(s.id)}>
                    {s.display_name || s.service}
                  </option>
                ))}
              </select>
            </label>

            <span className="hidden pb-2.5 text-slate-600 sm:block">
              <ArrowRight className="h-4 w-4" />
            </span>

            <label className="block">
              <span className="label">…depends on</span>
              <select className="input mt-1" value={callee} onChange={(e) => setCallee(e.target.value)}>
                <option value="">Choose the callee</option>
                {services
                  .filter((s) => String(s.id) !== caller)
                  .map((s) => (
                    <option key={String(s.id)} value={String(s.id)}>
                      {s.display_name || s.service}
                    </option>
                  ))}
              </select>
            </label>

            <label className="block">
              <span className="label">Over</span>
              <select className="input mt-1" value={protocol} onChange={(e) => setProtocol(e.target.value)}>
                {PROTOCOLS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {/* Read the edge back in words before it is written, because the
              direction is the one thing nobody notices getting wrong. */}
          {callerName && calleeName ? (
            <p className="rounded-lg border border-surface-border bg-surface-base px-3 py-2 text-xs text-slate-400">
              If <span className="text-slate-200">{calleeName.display_name || calleeName.service}</span>{" "}
              breaks, <span className="text-slate-200">{callerName.display_name || callerName.service}</span>{" "}
              is affected.
            </p>
          ) : null}

          <div className="flex justify-end gap-2">
            <button type="button" className="btn" onClick={close}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={action.busy || !caller || !callee || caller === callee}
            >
              {action.busy ? "Adding" : "Add dependency"}
            </button>
          </div>
        </form>
      ) : null}

      {action.parked ? (
        <ApprovalBanner approval={action.parked} message={action.message} onDismiss={action.reset} />
      ) : null}
      {action.error ? <ErrorState message={action.error} /> : null}
    </div>
  );
}
