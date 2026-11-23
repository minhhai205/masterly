import { NextRequest, NextResponse } from "next/server";
import { resolveBackendApiBase } from "./lib/backend-runtime-config";
import { prepareBackendForwardHeaders } from "./lib/backend-forward";
import {
  CODEX_CALLBACK_API_PATH,
  COOKIE_NAME,
  LOGIN_PATH,
  classifyToken,
  isAuthExempt,
  isBackendPath,
  isCodexCallbackPath,
  isWebSocketPath,
} from "./lib/proxy-policy";

// The browser only ever talks to the web app's origin. /api/*, /ws/* and
// /files/* are forwarded to the backend here, so no backend address is baked
// into the browser bundle.
const API_BASE_URL = resolveBackendApiBase();

function redirectToLogin(
  req: NextRequest,
  { clearCookie }: { clearCookie: boolean },
): NextResponse {
  const loginUrl = req.nextUrl.clone();
  loginUrl.pathname = LOGIN_PATH;
  loginUrl.search = "";
  loginUrl.searchParams.set(
    "next",
    `${req.nextUrl.pathname}${req.nextUrl.search}`,
  );
  const response = NextResponse.redirect(loginUrl);
  if (clearCookie) response.cookies.delete(COOKIE_NAME);
  return response;
}

export function proxy(req: NextRequest): NextResponse {
  const { pathname, search } = req.nextUrl;

  // A ChatGPT sign-in redirect arrives without a session; the backend matches
  // it to the waiting login by its one-time state.
  if (isCodexCallbackPath(pathname)) {
    return NextResponse.rewrite(new URL(CODEX_CALLBACK_API_PATH + search, API_BASE_URL));
  }

  if (isBackendPath(pathname)) {
    return NextResponse.rewrite(new URL(pathname + search, API_BASE_URL), {
      request: {
        headers: prepareBackendForwardHeaders(req.headers, {
          allowWebSocketUpgrade:
            req.method === "GET" && isWebSocketPath(pathname),
        }),
      },
    });
  }

  if (isAuthExempt(pathname)) {
    return NextResponse.next();
  }

  // Every page needs a session. An expired or broken cookie is cleared so the
  // login page does not bounce straight back.
  const token = req.cookies.get(COOKIE_NAME)?.value;
  if (classifyToken(token, Date.now()) !== "valid") {
    return redirectToLogin(req, { clearCookie: Boolean(token) });
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
