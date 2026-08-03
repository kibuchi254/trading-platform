/** BFF refresh route — swaps the refresh cookie for a new access cookie. */

import { cookies } from "next/headers";

const REFRESH_COOKIE = "atlas_refresh";
const ACCESS_COOKIE = "atlas_access";

export async function POST() {
  const cookieStore = await cookies();
  const refresh = cookieStore.get(REFRESH_COOKIE)?.value;
  if (!refresh) return Response.json({ ok: false }, { status: 401 });

  const res = await fetch(
    `${process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/auth/refresh`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    },
  );

  if (!res.ok) return Response.json({ ok: false }, { status: 401 });

  const tokens = await res.json();
  const response = Response.json({ ok: true });
  const secure = process.env.NODE_ENV === "production";
  response.headers.append(
    "Set-Cookie",
    `${ACCESS_COOKIE}=${tokens.access_token}; Max-Age=86400; Path=/; SameSite=Lax${secure ? "; Secure" : ""}`,
  );
  return response;
}
