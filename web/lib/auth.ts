import { apiFetch, apiUrl } from "@/lib/api";

// Sign-in is always on. Components read the session through `useAuthStatus`
// (web/hooks/useAuthStatus.ts), which calls `fetchAuthStatus` below.

export interface AuthStatus {
  authenticated: boolean;
  user_id?: string;
  email?: string;
  display_name?: string;
  role?: string;
  is_owner?: boolean;
  /** Avatar marker: "", "icon:<name>:<color>", or "img:<version>". */
  avatar?: string;
}

const AUTH_STATUS_CACHE_MS = 5_000;

let authStatusRequest: Promise<AuthStatus | null> | null = null;
let cachedAuthStatus: { value: AuthStatus | null; expiresAt: number } | null =
  null;

export function invalidateAuthStatusCache(): void {
  authStatusRequest = null;
  cachedAuthStatus = null;
}

/**
 * Ask the backend whether the current session is signed in.
 * Returns null on network error so callers can decide how to handle it.
 */
export function fetchAuthStatus(): Promise<AuthStatus | null> {
  if (cachedAuthStatus && cachedAuthStatus.expiresAt > Date.now()) {
    return Promise.resolve(cachedAuthStatus.value);
  }
  if (!authStatusRequest) {
    authStatusRequest = (async () => {
      try {
        const res = await apiFetch(apiUrl("/api/auth/status"));
        if (!res.ok) return null;
        return (await res.json()) as AuthStatus;
      } catch {
        return null;
      }
    })()
      .then((status) => {
        cachedAuthStatus = {
          value: status,
          // Retry an unreachable backend quickly; share stable answers across the
          // shell and the pages for one navigation.
          expiresAt: Date.now() + (status === null ? 1_000 : AUTH_STATUS_CACHE_MS),
        };
        return status;
      })
      .finally(() => {
        authStatusRequest = null;
      });
  }
  return authStatusRequest;
}

/** Create a group with its owner; the new owner is signed in on success. */
export async function register(
  email: string,
  password: string,
  displayName: string,
): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await apiFetch(apiUrl("/api/auth/register"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, display_name: displayName }),
      skipAuthRedirect: true,
    });
    if (res.ok) {
      invalidateAuthStatusCache();
      return { ok: true };
    }
    if (res.status === 422) {
      return { ok: false, error: "Check the email and use a password of at least 8 characters" };
    }
    const data = await res.json().catch(() => ({}));
    return { ok: false, error: extractDetail(data.detail) ?? "Registration failed" };
  } catch {
    return { ok: false, error: "Could not reach the server" };
  }
}

/** Send the credentials to the backend. */
export async function login(
  email: string,
  password: string,
): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await apiFetch(apiUrl("/api/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      // A 401 here means wrong credentials, not an expired session: show it in
      // the form instead of redirecting.
      skipAuthRedirect: true,
    });
    if (res.ok) {
      invalidateAuthStatusCache();
      return { ok: true };
    }
    const data = await res.json().catch(() => ({}));
    return { ok: false, error: extractDetail(data.detail) ?? "Login failed" };
  } catch {
    return { ok: false, error: "Could not reach the server" };
  }
}

/**
 * Normalise a FastAPI error detail to a plain string: either a string
 * (HTTPException) or a list of validation errors (422).
 */
function extractDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first === "object" && first !== null && "msg" in first)
      return String((first as { msg: unknown }).msg);
  }
  return "Request failed";
}

export async function logout(): Promise<void> {
  try {
    await apiFetch(apiUrl("/api/auth/logout"), { method: "POST" });
  } catch {
    // Ignore: the caller redirects regardless.
  } finally {
    invalidateAuthStatusCache();
  }
}
