// Pure request-routing policy for the Next.js middleware (web/proxy.ts).
//
// No dependency on `next/server`: these are plain functions that answer "what
// should happen to this request?", and proxy.ts turns the answers into
// rewrites and redirects.

export const LOGIN_PATH = "/login";
export const COOKIE_NAME = "masterly_token";

export function isBackendPath(pathname: string): boolean {
  return (
    pathname.startsWith("/api/") ||
    isWebSocketPath(pathname) ||
    pathname.startsWith("/files/")
  );
}

export function isWebSocketPath(pathname: string): boolean {
  return pathname === "/ws" || pathname.startsWith("/ws/");
}

const STATIC_ASSET =
  /\.(?:png|jpe?g|gif|svg|ico|webp|avif|woff2?|ttf|otf|txt|json|map|css|js|wasm)$/i;

/** Pages reachable without a session: the sign-in page and static assets. */
export function isAuthExempt(pathname: string): boolean {
  return (
    pathname.startsWith(LOGIN_PATH) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    STATIC_ASSET.test(pathname)
  );
}

export type TokenState = "missing" | "malformed" | "expired" | "valid";

/**
 * Cheap pre-check of the session cookie before the page loads. It only reads
 * the expiry; the backend still verifies the signature on every API call.
 */
export function classifyToken(
  token: string | undefined,
  nowMs: number,
): TokenState {
  if (!token) return "missing";
  const parts = token.split(".");
  if (parts.length !== 3) return "malformed";
  try {
    const payload = JSON.parse(
      Buffer.from(parts[1], "base64url").toString("utf-8"),
    );
    if (payload.exp && nowMs >= payload.exp * 1000) return "expired";
  } catch {
    return "malformed";
  }
  return "valid";
}
