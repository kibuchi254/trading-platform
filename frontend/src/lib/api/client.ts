/**
 * REST client for the ATLAS backend.
 *
 * Reads the access JWT from the `atlas_access` cookie (set by the /api/auth
 * BFF route) and sends it as `Authorization: Bearer`. On 401 it attempts a
 * single refresh via /api/auth/refresh before failing. All backend
 * PlatformError bodies ({code, message}) are normalized into ApiError.
 */

import type { ApiKey, TokenPair } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

const ACCESS_COOKIE = "atlas_access";

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

/** Read a cookie value by name (client-side only). */
export function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp("(?:^|; )" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "=([^;]*)"),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

export function getAccessToken(): string | null {
  return getCookie(ACCESS_COOKIE);
}

async function refreshTokens(): Promise<boolean> {
  try {
    const res = await fetch("/api/auth/refresh", { method: "POST" });
    return res.ok;
  } catch {
    return false;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | string[] | undefined | null>;
  signal?: AbortSignal;
  raw?: boolean; // return Response instead of parsed JSON
}

function buildQuery(query?: RequestOptions["query"]): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue;
    if (Array.isArray(v)) {
      for (const item of v) params.append(k, String(item));
    } else {
      params.set(k, String(v));
    }
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

let refreshing: Promise<boolean> | null = null;

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = `${API_URL}${path}${buildQuery(opts.query)}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";

  let res = await fetch(url, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

  // 401 → attempt a single concurrent refresh, then retry once.
  if (res.status === 401) {
    refreshing ??= refreshTokens();
    const ok = await refreshing;
    refreshing = null;
    if (ok) {
      const newToken = getAccessToken();
      if (newToken) headers.Authorization = `Bearer ${newToken}`;
      res = await fetch(url, {
        method: opts.method ?? "GET",
        headers,
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        signal: opts.signal,
      });
    }
  }

  if (opts.raw) return res as unknown as T;

  if (!res.ok) {
    let code = "http_error";
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      code = data.code ?? code;
      message = data.message ?? data.detail ?? message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(code, message, res.status);
  }

  // 204 / empty
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ── Auth BFF helpers (browser-side convenience) ─────────────────────────

export async function login(email: string, password: string): Promise<void> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(data.code ?? "auth_failed", data.message ?? "Login failed", res.status);
  }
}

export async function register(payload: {
  org_name: string;
  org_slug: string;
  email: string;
  password: string;
  display_name: string;
}): Promise<void> {
  const res = await fetch("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(data.code ?? "register_failed", data.message ?? "Registration failed", res.status);
  }
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" });
}

export async function createApiKey(name: string): Promise<ApiKey> {
  // Backend takes name as a query param.
  const res = await apiFetch<{ id: string; name: string; key_prefix: string; raw_key: string; scopes: string[] }>(
    `/api/v1/auth/api-keys?name=${encodeURIComponent(name)}`,
    { method: "POST" },
  );
  return res;
}

export type { TokenPair };
