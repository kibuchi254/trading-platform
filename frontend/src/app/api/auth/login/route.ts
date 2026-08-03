/**
 * BFF login route — proxies POST /api/v1/auth/login on the backend and stores
 * the access + refresh tokens in JS-readable cookies so that:
 *   - middleware.ts can guard /dashboard/* on SSR, and
 *   - the WS client can read the token to append ?token=.
 *
 * The raw password never touches the browser's local storage. Uses the
 * server-only API_URL (defaults to the browser URL for local dev).
 */

const API_URL = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://api:8000";

const ACCESS_COOKIE = "atlas_access";
const REFRESH_COOKIE = "atlas_refresh";

const cookieOptions = {
  httpOnly: false, // JS-readable so WS ?token= and client fetch can read it
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
};

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const res = await fetch(`${API_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: body.email, password: body.password }),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    return Response.json(
      { code: data.code ?? "auth_failed", message: data.message ?? data.detail ?? "Login failed" },
      { status: res.status },
    );
  }

  const tokens = await res.json();
  const response = Response.json({ ok: true });
  response.headers.append("Set-Cookie", `${ACCESS_COOKIE}=${tokens.access_token}; ${serialize(cookieOptions, 86400)}`);
  response.headers.append(
    "Set-Cookie",
    `${REFRESH_COOKIE}=${tokens.refresh_token}; ${serialize(cookieOptions, 2592000)}`,
  );
  return response;
}

function serialize(opts: Record<string, unknown>, maxAge: number): string {
  const parts = [`Max-Age=${maxAge}`, `Path=${opts.path}`, `SameSite=${opts.sameSite}`];
  if (opts.secure) parts.push("Secure");
  return parts.join("; ");
}
