"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getTenant, getToken, setTenant as persistTenant, setToken } from "./api";
import type { Capability, Me, TenantSummary } from "./types";

interface SessionValue {
  me: Me | null;
  loading: boolean;
  tenant: TenantSummary | null;
  tenants: TenantSummary[];
  capabilities: Record<string, Capability>;
  switchTenant: (id: string) => void;
  signOut: () => void;
  refreshCapabilities: () => void;
  can: (operationId: string) => Capability | undefined;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<Record<string, Capability>>({});

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    api<Me>("/auth/me", { noTenant: true })
      .then((payload) => {
        if (cancelled) return;
        setMe(payload);
        const stored = getTenant();
        const valid = payload.tenants.find((t) => t.id === stored) ?? payload.tenants[0];
        if (valid) {
          setTenantId(valid.id);
          persistTenant(valid.id);
        }
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  const refreshCapabilities = useCallback(() => {
    if (!tenantId) return;
    api<{ operations: Capability[] }>("/capabilities", { tenant: tenantId })
      .then((payload) => {
        const map: Record<string, Capability> = {};
        for (const op of payload.operations) map[op.operation_id] = op;
        setCapabilities(map);
      })
      .catch(() => setCapabilities({}));
  }, [tenantId]);

  useEffect(() => {
    refreshCapabilities();
  }, [refreshCapabilities]);

  const switchTenant = useCallback(
    (id: string) => {
      setTenantId(id);
      persistTenant(id);
      router.refresh();
    },
    [router],
  );

  const signOut = useCallback(() => {
    setToken(null);
    persistTenant(null);
    router.replace("/login");
  }, [router]);

  const value = useMemo<SessionValue>(() => {
    const tenants = me?.tenants ?? [];
    return {
      me,
      loading,
      tenants,
      tenant: tenants.find((t) => t.id === tenantId) ?? null,
      capabilities,
      switchTenant,
      signOut,
      refreshCapabilities,
      can: (operationId: string) => capabilities[operationId],
    };
  }, [me, loading, tenantId, capabilities, switchTenant, signOut, refreshCapabilities]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}

/** Small data hook: fetch on mount and whenever the tenant changes. */
export function useApi<T>(
  path: string | null,
  options: { query?: Record<string, string | number | boolean | null | undefined>; noTenant?: boolean } = {},
) {
  const { tenant } = useSession();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const queryKey = JSON.stringify(options.query ?? {});

  useEffect(() => {
    if (!path || (!tenant && !options.noTenant)) return;
    let cancelled = false;
    setLoading(true);
    api<T>(path, { query: options.query, noTenant: options.noTenant })
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
          setError(null);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tenant?.id, queryKey, nonce, options.noTenant]);

  return { data, error, loading, reload: () => setNonce((n) => n + 1) };
}
