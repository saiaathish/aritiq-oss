import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

// Force Node.js runtime — the Supabase JS client uses `process.version` which
// is unavailable in Edge Runtime and causes FUNCTION_INVOCATION_FAILED on Vercel.
export const runtime = "nodejs";

/**
 * Refreshes the Supabase session cookie on every matched request and gates the
 * product UI: unauthenticated visits to /app redirect to /login (with a `next`
 * param so the callback can land them back where they were headed). The
 * marketing landing page at `/` stays public.
 */
export async function middleware(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // If Supabase env vars are missing, skip auth gating entirely so the
  // deployment doesn't crash with a 500 on every matched route.
  if (!supabaseUrl || !supabaseKey) {
    console.warn("Supabase env vars missing — skipping auth middleware");
    return response;
  }

  const supabase = createServerClient(
    supabaseUrl,
    supabaseKey,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (cookiesToSet) => {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  // IMPORTANT: getUser() validates the JWT against Supabase — don't swap for
  // getSession(), which trusts the (spoofable) cookie contents.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname, search } = request.nextUrl;

  // IMPORTANT: when the middleware redirects, it must CARRY OVER any cookies
  // `setAll` just wrote onto `response` — otherwise a freshly refreshed Supabase
  // session is silently discarded and the user sees a "still signed out" page
  // on the very next render. Forward only the Set-Cookie headers, not the
  // whole header bag (avoids leaking other Next.js-internal headers across
  // redirects).
  function redirectPreservingCookies(url: URL): NextResponse {
    const redirectRes = NextResponse.redirect(url);
    const setCookies =
      typeof response.headers.getSetCookie === "function"
        ? response.headers.getSetCookie()
        : [];
    for (const cookie of setCookies) {
      redirectRes.headers.append("Set-Cookie", cookie);
    }
    return redirectRes;
  }

  if (!user && pathname.startsWith("/app")) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    url.searchParams.set("next", `${pathname}${search}`);
    return redirectPreservingCookies(url);
  }

  if (user && pathname === "/login") {
    const url = request.nextUrl.clone();
    url.pathname = "/app";
    url.search = "";
    return redirectPreservingCookies(url);
  }

  return response;
}

export const config = {
  matcher: ["/app/:path*", "/app", "/login"],
};
