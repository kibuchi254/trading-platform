/** BFF register route — proxies POST /api/v1/auth/register (org + admin bootstrap). */

const API_URL = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://api:8000";

const ACCESS_COOKIE = "atlas_access";
const REFRESH_COOKIE = "atlas_refresh";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const res = await fetch(`${API_URL}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    return Response.json(
      { code: data.code ?? "register_failed", message: data.message ?? data.detail ?? "Registration failed" },
      { status: res.status },
    );
  }

  const tokens = await res.json();
  const response = Response.json({ ok: true });
  const secure = process.env.NODE_ENV === "production";
  response.headers.append(
    "Set-Cookie",
    `${ACCESS_COOKIE}=${tokens.access_token}; Max-Age=86400; Path=/; SameSite=Lax${secure ? "; Secure" : ""}`,
  );
  response.headers.append(
    "Set-Cookie",
    `${REFRESH_COOKIE}=${tokens.refresh_token}; Max-Age=2592000; Path=/; SameSite=Lax${secure ? "; Secure" : ""}`,
  );
  return response;
}
