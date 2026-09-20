"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BellRing,
  Brain,
  Building2,
  CalendarClock,
  GitMerge,
  Globe2,
  Layers,
  ListChecks,
  LayoutDashboard,
  LogOut,
  Network,
  PlugZap,
  Regex,
  ScrollText,
  ShieldCheck,
  Siren,
  Table2,
  Workflow,
} from "lucide-react";
import { SessionProvider, useSession } from "@/lib/session";
import { Spinner } from "@/components/ui";

// Mirrors Keep's own navigation, section for section, so anyone who knows Keep
// can find their way around immediately — plus the two groups that are
// Chetana's rather than Keep's: the estate view and the governance layer.
const NAV: { section: string; items: { href: string; label: string; icon: typeof Activity }[] }[] = [
  {
    section: "Chetana",
    items: [
      { href: "/overview", label: "Overview", icon: Activity },
      { href: "/estate", label: "Operations Overview", icon: Globe2 },
    ],
  },
  {
    section: "Incidents",
    items: [
      { href: "/incidents", label: "Incidents", icon: Siren },
      // Investigations used to be reachable only from the incident they
      // belonged to, so finding a past root cause meant already knowing which
      // incident to open.
      { href: "/investigations", label: "Root cause analysis", icon: Brain },
    ],
  },
  {
    section: "Alerts",
    items: [{ href: "/alerts", label: "Feed", icon: BellRing }],
  },
  {
    section: "Noise reduction",
    items: [
      { href: "/deduplication", label: "Deduplication", icon: Layers },
      { href: "/correlations", label: "Correlations", icon: GitMerge },
      { href: "/workflows", label: "Workflows", icon: Workflow },
      // What is worth turning into a workflow, derived from ticket history.
      { href: "/runbooks", label: "Runbook candidates", icon: ListChecks },
      { href: "/topology", label: "Service Topology", icon: Network },
      { href: "/mapping", label: "Mapping", icon: Table2 },
      { href: "/extraction", label: "Extraction", icon: Regex },
      { href: "/maintenance", label: "Maintenance Windows", icon: CalendarClock },
      // AI Plugins is deliberately not linked. Keep supplies those models and
      // reports none for a tenant until it has a body of alert history, so the
      // page is empty for every client we currently run — and a nav item that
      // always opens onto nothing teaches people to distrust the rest of the
      // nav. The page still exists at /ai-plugins; restore this line when Keep
      // starts returning models.
    ],
  },
  {
    section: "Dashboards",
    items: [{ href: "/dashboards", label: "Dashboards", icon: LayoutDashboard }],
  },
  {
    section: "Governance",
    items: [
      { href: "/approvals", label: "Approvals", icon: ShieldCheck },
      { href: "/governance", label: "Allowlist & audit", icon: ScrollText },
      { href: "/providers", label: "Providers", icon: PlugZap },
    ],
  },
];

/**
 * Switching client, as a control rather than a block in the navigation.
 *
 * It used to sit at the top of the sidebar with its own "CLIENT" heading and
 * the autonomy ceiling under it — three lines of chrome above the nav, on every
 * page, restating what the page title already says.
 *
 * It renders only when there is more than one client to switch between. A
 * dropdown with a single option is furniture: it costs vertical space, invites
 * a click that does nothing, and says nothing the heading does not.
 */
function TenantSwitcher() {
  const { tenants, tenant, switchTenant } = useSession();
  if (tenants.length < 2) return null;

  return (
    <div className="flex items-center gap-2">
      <Building2 className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
      <label className="sr-only" htmlFor="tenant">
        Client
      </label>
      <select
        id="tenant"
        className="input w-auto appearance-none py-1 pl-2 pr-7 text-[13px] font-medium"
        value={tenant?.id ?? ""}
        onChange={(e) => switchTenant(e.target.value)}
      >
        {tenants.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Renders nothing at all for a single-client deployment. */
function ContextBar() {
  const { tenants } = useSession();
  if (tenants.length < 2) return null;
  return (
    <div className="flex items-center justify-end gap-3 border-b border-white/10 bg-white/[0.04] px-7 py-2 backdrop-blur">
      <TenantSwitcher />
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { me, loading, signOut } = useSession();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Opening console" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      {/* Glass rather than a solid panel, so the sky carries behind the rail
          exactly as it does behind the marketing site's own chrome. */}
      <aside className="glass sticky top-0 flex h-screen w-60 shrink-0 flex-col rounded-none border-y-0 border-l-0">
        {/* The marketing site's own mark — a blue ring with a lit core —
            rather than a second logo invented for the console. It replaced an
            Intertec-red shield, which is no loss: that red measures ΔE 8.1
            from critical-severity red, so it could never safely sit near an
            alert anyway. */}
        <div className="flex items-center gap-2.5 border-b border-white/10 px-4 py-3.5">
          <span className="relative block h-[26px] w-[26px] shrink-0 rounded-full border-[3px] border-[#3B82F6] shadow-[0_0_14px_rgba(59,130,246,.75)]">
            <span className="absolute inset-[5px] rounded-full bg-[#60A5FA]" />
          </span>
          <div className="min-w-0">
            <p className="text-[15px] font-semibold leading-none tracking-[-0.01em] text-ink">
              Chetana AI
            </p>
            <p className="mt-1 text-[10px] font-medium uppercase tracking-[0.09em] text-ink-muted">
              by Intertec
            </p>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 pb-2">
          {NAV.map(({ section, items }) => (
            <div key={section} className="mb-0.5">
              <p className="px-3 pb-1 pt-2.5 text-[10px] font-semibold uppercase tracking-[0.09em] text-ink-faint">
                {section}
              </p>
              {items.map(({ href, label, icon: Icon }) => {
                // No nav href is a prefix of another, so startsWith is safe and
                // keeps a child route (/incidents/123) lighting up its parent.
                const active = pathname.startsWith(href);
                return (
                  <Link
                    key={href}
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={`relative flex items-center gap-2.5 rounded-lg py-1 pl-3 pr-2 text-[13px] transition ${
                      active
                        ? "bg-white/10 font-semibold text-white"
                        : "text-ink-2 hover:bg-white/[0.06] hover:text-ink"
                    }`}
                  >
                    {active ? (
                      <span
                        aria-hidden
                        className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-accent"
                      />
                    ) : null}
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="truncate">{label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="space-y-2.5 border-t border-white/10 px-4 py-3">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-ink-2" title={me?.email}>
                {me?.email}
              </p>
              <p className="mt-0.5 text-[10px] font-semibold uppercase tracking-[0.09em] text-ink-faint">
                {me?.role}
              </p>
            </div>
          </div>
          <button className="btn w-full justify-center py-1.5" onClick={signOut}>
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <ContextBar />
        <main className="min-w-0 flex-1 animate-fade-up px-7 py-7">{children}</main>
      </div>
    </div>
  );
}

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <Shell>{children}</Shell>
    </SessionProvider>
  );
}
