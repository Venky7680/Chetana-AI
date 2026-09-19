"use client";

const BASE = process.env.NEXT_PUBLIC_BFF_URL ?? "http://localhost:8080";
const API = `${BASE}/api/v1`;

const TOKEN_KEY = "chetana.token";
const TENANT_KEY = "chetana.tenant";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

export function getTenant(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TENANT_KEY);
}

export function setTenant(tenant: string | null) {
  if (typeof window === "undefined") return;
  if (tenant) window.localStorage.setItem(TENANT_KEY, tenant);
  else window.localStorage.removeItem(TENANT_KEY);
}

/** The BFF parks an action instead of running it. Not an error — a workflow step. */
export class ApprovalRequired extends Error {
  constructor(
    public approval: import("./types").ApprovalRequest,
    message: string,
  ) {
    super(message);
    this.name = "ApprovalRequired";
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  tenant?: string | null;
  query?: Record<string, string | number | boolean | null | undefined>;
  /** Some calls (the estate view) are deliberately cross-tenant. */
  noTenant?: boolean;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, noTenant } = options;

  const url = new URL(`${API}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (!noTenant) {
    const tenant = options.tenant ?? getTenant();
    if (tenant) headers["X-Chetana-Tenant"] = tenant;
  }

  const response = await fetch(url.toString(), {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });

  if (response.status === 401) {
    setToken(null);
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Session expired");
  }

  const text = await response.text();
  const payload = text ? safeJson(text) : null;

  if (response.status === 202 && isApprovalPayload(payload)) {
    const detail = (payload as { detail: { message: string; approval: import("./types").ApprovalRequest } })
      .detail;
    throw new ApprovalRequired(detail.approval, detail.message);
  }

  if (!response.ok) {
    throw new ApiError(response.status, extractMessage(payload) ?? `Request failed (${response.status})`);
  }

  return payload as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

function isApprovalPayload(payload: unknown): boolean {
  return (
    typeof payload === "object" &&
    payload !== null &&
    typeof (payload as { detail?: unknown }).detail === "object" &&
    (payload as { detail: { code?: string } }).detail?.code === "approval_required"
  );
}

function extractMessage(payload: unknown): string | null {
  if (typeof payload === "string") return payload;
  if (typeof payload === "object" && payload !== null) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (typeof detail === "object" && detail !== null) {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === "string") return message;
    }
  }
  return null;
}

export async function login(email: string, password: string) {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const payload = safeJson(await response.text());
    throw new ApiError(response.status, extractMessage(payload) ?? "Sign-in failed");
  }
  return (await response.json()) as {
    access_token: string;
    expires_in: number;
    role: string;
    email: string;
  };
}

/**
 * Upload a file.
 *
 * Separate from `api` on purpose: that helper sets a JSON content type and
 * stringifies the body, both of which break multipart. The browser must set
 * Content-Type itself here so it can add the boundary — setting it by hand is
 * the classic way to get a 422 that reads like a validation error.
 */
export async function upload<T>(
  path: string,
  file: File,
  options: { field?: string; tenant?: string | null } = {},
): Promise<T> {
  const form = new FormData();
  form.append(options.field ?? "file", file);

  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const tenant = options.tenant ?? getTenant();
  if (tenant) headers["X-Chetana-Tenant"] = tenant;

  const response = await fetch(`${API}${path}`, { method: "POST", headers, body: form });

  if (response.status === 401) {
    setToken(null);
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Session expired");
  }

  const text = await response.text();
  const payload = text ? safeJson(text) : null;
  if (!response.ok) {
    throw new ApiError(
      response.status,
      extractMessage(payload) ?? `Upload failed (${response.status})`,
    );
  }
  return payload as T;
}
