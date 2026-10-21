import { NextResponse, type NextRequest } from "next/server";

// Signed-out visitors go to the sign-in page. The API still checks every request; this only
// avoids flashing an empty dashboard. Every notification link therefore needs a signed-in session.
const PUBLIC = ["/login", "/signup", "/trust", "/api", "/_next", "/favicon", "/icon", "/sw.js", "/manifest"];

export function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (PUBLIC.some((p) => pathname === p || pathname.startsWith(p + "/") || pathname.startsWith(p))) {
    return NextResponse.next();
  }
  if (!req.cookies.get("lintel_session")) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
