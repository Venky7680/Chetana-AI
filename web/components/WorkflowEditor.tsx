"use client";

import { useState } from "react";
import { FileCode2, X } from "lucide-react";
import { GatedAction } from "./ui";
import type { Capability } from "@/lib/types";

/**
 * Keep workflows are YAML. Rather than a form that can only express the shapes
 * I anticipated, this is the YAML itself with starter templates — an engineer
 * can write anything Keep supports without leaving the console, and the
 * templates mean nobody starts from a blank page.
 */

export interface Template {
  label: string;
  blurb: string;
  yaml: string;
}

export const TEMPLATES: Template[] = [
  {
    label: "Notify on critical",
    blurb: "Fires on any critical alert and posts a summary. Safe first workflow — it only reads.",
    yaml: `workflow:
  id: notify-on-critical
  name: Notify on critical
  description: Posts a summary whenever a critical alert arrives.
  triggers:
    - type: alert
      filters:
        - key: severity
          value: critical
  actions:
    - name: log-summary
      provider:
        type: console
        with:
          message: |
            CRITICAL on {{ alert.service }} in {{ alert.environment }}
            {{ alert.name }} — {{ alert.description }}
            Runbook: {{ alert.runbook }}
`,
  },
  {
    label: "Enrich from the incident",
    blurb: "On a new incident, writes the owning team onto every alert inside it.",
    yaml: `workflow:
  id: enrich-incident-owner
  name: Enrich incident with owner
  description: Stamps the owning team onto alerts when an incident is created.
  triggers:
    - type: incident
      events:
        - created
  actions:
    - name: annotate
      provider:
        type: console
        with:
          message: |
            Incident {{ incident.name }} covers {{ incident.services }}.
            Owner lookup comes from the Mapping rules.
`,
  },
  {
    label: "Scheduled health digest",
    blurb: "Runs on an interval rather than an alert — useful for a daily estate summary.",
    yaml: `workflow:
  id: daily-health-digest
  name: Daily health digest
  description: Summarises the estate once a day.
  triggers:
    - type: interval
      value: 86400
  actions:
    - name: digest
      provider:
        type: console
        with:
          message: Daily digest for the estate.
`,
  },
  {
    label: "Empty",
    blurb: "Start from the minimum Keep accepts.",
    yaml: `workflow:
  id: my-workflow
  name: My workflow
  description: What this automation does and when it should run.
  triggers:
    - type: manual
  actions:
    - name: first-step
      provider:
        type: console
        with:
          message: Hello from Chetana.
`,
  },
];

export function WorkflowEditor({
  initialYaml,
  title,
  capability,
  busy,
  onSubmit,
  onCancel,
  showTemplates = true,
}: {
  initialYaml?: string;
  title: string;
  capability: Capability | undefined;
  busy?: boolean;
  onSubmit: (yaml: string) => void;
  onCancel: () => void;
  showTemplates?: boolean;
}) {
  const [yaml, setYaml] = useState(initialYaml ?? TEMPLATES[0].yaml);
  const [problem, setProblem] = useState<string | null>(null);

  function check(text: string): string | null {
    // Not a YAML parser — just the mistakes that produce a confusing 400 from
    // Keep, caught before the round trip.
    if (!text.trim()) return "The definition is empty.";
    if (!/^\s*workflow\s*:/m.test(text)) {
      return 'A Keep workflow must start with a top-level "workflow:" key.';
    }
    if (!/^\s+id\s*:/m.test(text)) return 'The workflow needs an "id".';
    if (!/^\s+triggers\s*:/m.test(text)) {
      return 'The workflow needs a "triggers:" list, even if it is just "- type: manual".';
    }
    if (text.includes("\t")) {
      return "YAML does not allow tabs for indentation — use spaces.";
    }
    return null;
  }

  function submit() {
    const found = check(yaml);
    setProblem(found);
    if (!found) onSubmit(yaml);
  }

  return (
    <section className="card-pad space-y-3">
      <div className="flex items-start justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <FileCode2 className="h-4 w-4 text-slate-500" />
          {title}
        </h2>
        <button className="text-slate-500 hover:text-slate-300" onClick={onCancel} aria-label="Close">
          <X className="h-4 w-4" />
        </button>
      </div>

      {showTemplates ? (
        <div className="flex flex-wrap gap-1.5">
          {TEMPLATES.map((template) => (
            <button
              key={template.label}
              title={template.blurb}
              onClick={() => {
                setYaml(template.yaml);
                setProblem(null);
              }}
              className="rounded-md border border-surface-border px-2 py-1 text-xs text-slate-500 transition hover:border-slate-500 hover:text-slate-300"
            >
              {template.label}
            </button>
          ))}
        </div>
      ) : null}

      <textarea
        spellCheck={false}
        className="input h-96 resize-y font-mono text-xs leading-relaxed"
        value={yaml}
        onChange={(e) => {
          setYaml(e.target.value);
          if (problem) setProblem(null);
        }}
      />

      {problem ? (
        <p className="rounded-lg border border-sev-critical/30 bg-sev-critical/5 px-3 py-2 text-xs text-sev-critical">
          {problem}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <GatedAction capability={capability} busy={busy} onClick={submit}>
          Save to Keep
        </GatedAction>
        <button className="btn" onClick={onCancel}>
          Cancel
        </button>
        <span className="text-xs text-slate-600">
          Creating a workflow is tier R2 — it can act on the client estate.
        </span>
      </div>
    </section>
  );
}
