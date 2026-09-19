"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, BookOpen, KeyRound, Search, ShieldAlert, Webhook } from "lucide-react";
import { api } from "@/lib/api";
import type { Capability, ProviderCatalogueEntry, ProviderConfigField } from "@/lib/types";
import { Markdown } from "@/components/Markdown";
import { GatedAction, Spinner } from "@/components/ui";

/**
 * Connect a telemetry source without ever opening Keep.
 *
 * Keep's own install screen is good, and everything that makes it good is data
 * Keep already publishes per provider: the field labels and hints, which fields
 * are optional, the scopes the credential must carry, whether the source can be
 * polled or must push. An earlier version of this form kept four booleans from
 * that payload and threw the rest away, which is why it was so much thinner.
 * Now the whole thing is rendered, for all ~124 providers, from one schema.
 *
 * What is typed here is a client's credential. It goes to the BFF, which
 * forwards it to Keep's secret manager and keeps it out of logs, the audit
 * trail and the approval ledger. It lives in component state until the request
 * returns, and is cleared immediately after.
 */

interface WebhookSettings {
  markdown: string | null;
  description: string | null;
  template: string | null;
}

function isSensitive(name: string, field: ProviderConfigField): boolean {
  if (field.sensitive) return true;
  // Keep does not set `sensitive` on every credential field. Err towards
  // masking: revealing a token is a worse mistake than masking a hostname.
  return /key|token|secret|password|passwd|credential|private/i.test(name);
}

/** Plain HTTP means the credential crosses the network in clear text. On a
 *  laptop that is nothing; anywhere else it is the whole ballgame. */
function insecureTransport(): boolean {
  if (typeof window === "undefined") return false;
  const { protocol, hostname } = window.location;
  if (protocol === "https:") return false;
  return !["localhost", "127.0.0.1", "[::1]"].includes(hostname);
}

const KEEP_DOCS = "https://docs.keephq.dev/providers/documentation";

export function ProviderInstall({
  catalogue,
  capability,
  busy,
  onInstall,
  onCancel,
}: {
  catalogue: ProviderCatalogueEntry[];
  capability: Capability | undefined;
  busy?: boolean;
  onInstall: (payload: {
    provider_id: string;
    provider_name: string;
    provider_type: string;
    pulling_enabled: boolean;
    config: Record<string, string | boolean>;
  }) => Promise<unknown>;
  onCancel: () => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ProviderCatalogueEntry | null>(null);
  const [name, setName] = useState("");
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [pulling, setPulling] = useState(true);
  const [webhook, setWebhook] = useState<WebhookSettings | null>(null);
  const [webhookLoading, setWebhookLoading] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? catalogue.filter((p) =>
          `${p.display_name} ${p.type} ${(p.categories ?? []).join(" ")} ${(p.tags ?? []).join(" ")}`
            .toLowerCase()
            .includes(q),
        )
      : catalogue;
    return list.slice(0, 36);
  }, [catalogue, query]);

  const [required, optional] = useMemo(() => {
    const config = (selected?.config ?? {}) as Record<string, ProviderConfigField>;
    const entries = Object.entries(config).filter(([, f]) => f && typeof f === "object");
    return [entries.filter(([, f]) => f.required), entries.filter(([, f]) => !f.required)];
  }, [selected]);

  // Fetch the push instructions as soon as a source that supports them is
  // picked — they are often the whole setup, not an afterthought.
  useEffect(() => {
    if (!selected?.supports_webhook) {
      setWebhook(null);
      return;
    }
    let cancelled = false;
    setWebhookLoading(true);
    api<WebhookSettings>(`/providers/${encodeURIComponent(selected.type)}/webhook`)
      .then((result) => {
        if (!cancelled) setWebhook(result);
      })
      .catch(() => {
        if (!cancelled) setWebhook(null);
      })
      .finally(() => {
        if (!cancelled) setWebhookLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  function choose(provider: ProviderCatalogueEntry) {
    setSelected(provider);
    setName(provider.display_name || provider.type);
    setProblem(null);
    setPulling(true);
    // Seed defaults so a form that is already valid does not look empty.
    const config = (provider.config ?? {}) as Record<string, ProviderConfigField>;
    const seeded: Record<string, string | boolean> = {};
    for (const [key, field] of Object.entries(config)) {
      if (field?.default !== undefined && field.default !== null) {
        seeded[key] = field.default as string | boolean;
      }
    }
    setValues(seeded);
  }

  async function submit() {
    if (!selected) return;
    const missing = required
      .filter(([key]) => {
        const value = values[key];
        return typeof value === "boolean" ? false : !String(value ?? "").trim();
      })
      .map(([key, field]) => field.description || key);

    if (missing.length > 0) {
      setProblem(`Keep needs ${missing.join(", ")} for this source.`);
      return;
    }
    setProblem(null);

    const slug =
      name
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "") || selected.type;

    await onInstall({
      provider_id: slug,
      provider_name: name.trim() || selected.display_name,
      provider_type: selected.type,
      pulling_enabled: selected.pulling_available ? pulling : false,
      config: Object.fromEntries(
        Object.entries(values).filter(([, v]) => v !== undefined && v !== ""),
      ),
    });

    // Do not leave the credential sitting in component state afterwards.
    setValues({});
  }

  function field([key, spec]: [string, ProviderConfigField]) {
    const value = values[key];
    const type = String(spec.type ?? "").toLowerCase();
    const boolean = type === "bool" || type === "boolean" || typeof spec.default === "boolean";

    return (
      <label key={key} className="block">
        <span className="label mb-1.5 block">
          {spec.description || key}
          {spec.required ? <span className="text-sev-critical"> *</span> : null}
        </span>
        {boolean ? (
          <span className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={Boolean(value)}
              onChange={(e) => setValues({ ...values, [key]: e.target.checked })}
              className="h-3.5 w-3.5 rounded border-surface-border bg-surface-base accent-accent"
            />
            {Boolean(value) ? "on" : "off"}
          </span>
        ) : (
          <input
            className="input font-mono text-xs"
            type={isSensitive(key, spec) ? "password" : "text"}
            autoComplete="off"
            spellCheck={false}
            placeholder={`Enter ${key}`}
            value={typeof value === "string" ? value : ""}
            onChange={(e) => {
              setValues({ ...values, [key]: e.target.value });
              if (problem) setProblem(null);
            }}
          />
        )}
        {spec.hint ? (
          <span className="mt-1 block text-xs text-slate-600">{spec.hint}</span>
        ) : null}
      </label>
    );
  }

  // ------------------------------------------------------------------ picker
  if (!selected) {
    return (
      <section className="card-pad space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <KeyRound className="h-4 w-4 text-slate-500" />
              Connect a telemetry source
            </h2>
            <p className="mt-1 max-w-2xl text-xs text-slate-600">
              {catalogue.length} sources available. Credentials go straight to this
              client&apos;s Keep secret manager — Chetana does not log them, write them to the
              audit trail, or hold them while an install waits for approval.
            </p>
          </div>
          <button className="btn" onClick={onCancel}>
            Cancel
          </button>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-600" />
          <input
            className="input pl-8"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="datadog, servicenow, azure, graylog, prometheus…"
          />
        </div>

        <div className="grid max-h-[26rem] gap-2 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
          {matches.map((provider) => (
            <button
              key={provider.type}
              onClick={() => choose(provider)}
              disabled={provider.coming_soon}
              className="rounded-lg border border-surface-border px-3 py-2 text-left transition hover:border-accent/50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <p className="truncate text-sm text-slate-200">{provider.display_name}</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {provider.supports_webhook ? <span className="chip">webhook</span> : null}
                {provider.can_query ? <span className="chip">query</span> : null}
                {provider.can_notify ? <span className="chip">notify</span> : null}
                {provider.coming_soon ? <span className="chip">coming soon</span> : null}
              </div>
            </button>
          ))}
          {matches.length === 0 ? (
            <p className="col-span-full text-sm text-slate-600">Nothing matches that.</p>
          ) : null}
        </div>
      </section>
    );
  }

  // ------------------------------------------------------------------- form
  const scopes = selected.scopes ?? [];

  return (
    <section className="card-pad space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <button
            className="mb-2 inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300"
            onClick={() => setSelected(null)}
          >
            <ArrowLeft className="h-3 w-3" />
            All sources
          </button>
          <h2 className="text-sm font-semibold text-slate-200">
            Connect to {selected.display_name}
          </h2>
          {selected.description ? (
            <p className="mt-1 max-w-2xl text-xs text-slate-600">{selected.description}</p>
          ) : null}
          <a
            href={
              selected.docs_slug ? `${KEEP_DOCS}/${selected.docs_slug}` : KEEP_DOCS
            }
            target="_blank"
            rel="noreferrer noopener"
            className="mt-2 inline-flex items-center gap-1.5 text-xs text-accent hover:underline"
          >
            <BookOpen className="h-3 w-3" />
            Provider documentation
          </a>
        </div>
        <span className="chip shrink-0 font-mono">{selected.type}</span>
      </div>

      {insecureTransport() ? (
        <p className="flex items-start gap-2 rounded-lg border border-sev-critical/40 bg-sev-critical/5 px-3 py-2 text-xs text-sev-critical">
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            This console is served over plain HTTP, so anything typed below crosses the network
            in clear text. Put TLS in front of Chetana before entering a real client credential.
          </span>
        </p>
      ) : null}

      {scopes.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-surface-border">
          <div className="border-b border-surface-border bg-surface-overlay/40 px-4 py-2">
            <p className="text-xs font-medium text-slate-300">
              What the credential must be allowed to do
            </p>
            <p className="mt-0.5 text-xs text-slate-600">
              Check these before you generate the token — a read-only key that is missing a
              mandatory scope fails at install, not here.
            </p>
          </div>
          <table className="w-full">
            <tbody>
              {scopes.map((scope) => (
                <tr key={scope.name} className="row">
                  <td className="td align-top font-mono text-xs text-slate-300">
                    {scope.name}
                    {scope.mandatory ? <span className="text-sev-critical">*</span> : null}
                  </td>
                  <td className="td align-top text-xs text-slate-500">
                    {scope.description ?? "—"}
                    {scope.mandatory_for_webhook && !scope.mandatory ? (
                      <span className="mt-0.5 block text-slate-600">
                        Required only if Keep installs the webhook for you.
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <label className="block">
        <span className="label mb-1.5 block">
          Name it<span className="text-sev-critical"> *</span>
        </span>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={`${selected.display_name} (production)`}
        />
        <span className="mt-1 block text-xs text-slate-600">
          How this source appears across the console. Use something an on-call engineer will
          recognise at 3am.
        </span>
      </label>

      {required.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2">{required.map(field)}</div>
      ) : null}

      {optional.length > 0 ? (
        <details className="rounded-lg border border-surface-border px-4 py-3">
          <summary className="cursor-pointer text-xs font-medium text-slate-400">
            Optional settings ({optional.length})
          </summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">{optional.map(field)}</div>
        </details>
      ) : null}

      {selected.pulling_available ? (
        <label className="flex items-start gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={pulling}
            onChange={(e) => setPulling(e.target.checked)}
            className="mt-1 h-3.5 w-3.5 rounded border-surface-border bg-surface-base accent-accent"
          />
          <span>
            Poll this source for alerts
            <span className="mt-0.5 block text-xs text-slate-600">
              Keep fetches on a schedule instead of waiting to be pushed to. Leave on unless the
              source will push to the webhook below.
            </span>
          </span>
        </label>
      ) : null}

      {problem ? (
        <p className="rounded-lg border border-sev-critical/30 bg-sev-critical/5 px-3 py-2 text-xs text-sev-critical">
          {problem}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <GatedAction capability={capability} busy={busy} onClick={submit}>
          Connect
        </GatedAction>
        <button className="btn" onClick={onCancel}>
          Cancel
        </button>
        <span className="text-xs text-slate-600">
          Keep validates the credential against the scopes above and refuses the install if any
          mandatory one is missing.
        </span>
      </div>

      {selected.supports_webhook ? (
        <div className="rounded-lg border border-surface-border">
          <div className="border-b border-surface-border px-4 py-2.5">
            <p className="flex items-center gap-2 text-xs font-medium text-slate-300">
              <Webhook className="h-3.5 w-3.5 text-slate-500" />
              Push alerts from {selected.display_name} instead
            </p>
            <p className="mt-0.5 text-xs text-slate-600">
              No credential needed — point {selected.display_name} at this URL and it sends
              alerts in. The key below is Keep&apos;s webhook key for this client; it is meant to
              be copied into the source.
            </p>
          </div>
          <div className="px-4 py-3">
            {webhookLoading ? (
              <Spinner label="Reading the webhook settings" />
            ) : webhook?.markdown ? (
              <Markdown text={webhook.markdown} />
            ) : webhook?.description ? (
              <Markdown text={webhook.description} />
            ) : (
              <p className="text-xs text-slate-600">
                Keep did not return push instructions for this source. Its webhook usually needs
                an external URL configured on the Keep container (KEEP_API_URL); until then the
                credential route above is the one that works.
              </p>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}
