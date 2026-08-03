import { NextResponse, type NextRequest } from "next/server";

/**
 * Guard the dashboard. If no `atlas_access` cookie, redirect to login.
 * The token is JS-readable, so this is an auth *gate*, not a secrecy
 * boundary — the backend re-validates the JWT on every request.
 */
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const token = req.cookies.get("atlas_access")?.value;

  if (!token) {
    const url = req.nextUrl.clone();
    url.pathname = "/auth/v1/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*"],
};
