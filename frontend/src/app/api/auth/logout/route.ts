/** BFF logout route — clears the access + refresh cookies. */

export async function POST() {
  const response = Response.json({ ok: true });
  const expired = "Max-Age=0; Path=/; SameSite=Lax";
  response.headers.append("Set-Cookie", `atlas_access=; ${expired}`);
  response.headers.append("Set-Cookie", `atlas_refresh=; ${expired}`);
  return response;
}
