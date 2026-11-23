"use client";

import { useEffect, useState } from "react";
import { fetchAuthStatus } from "@/lib/auth";

export interface AuthStatusState {
  /** Whether the current session is authenticated. */
  authenticated: boolean;
  /** Whether the authenticated user owns the group. */
  isOwner: boolean;
  /** Stable account id for account-scoped browser state. */
  userId: string | null;
  /** False when the runtime status endpoint could not be reached. */
  statusAvailable: boolean;
  /** True until the first status fetch resolves. */
  loading: boolean;
}

const INITIAL: AuthStatusState = {
  authenticated: false,
  isOwner: false,
  userId: null,
  statusAvailable: false,
  loading: true,
};

/** Resolve the session from the backend (`/api/auth/status`). */
function loadAuthStatus(): Promise<AuthStatusState> {
  return fetchAuthStatus().then((status) => ({
    authenticated: Boolean(status?.authenticated),
    isOwner: Boolean(status?.is_owner),
    userId:
      typeof status?.user_id === "string" && status.user_id.trim()
        ? status.user_id
        : null,
    statusAvailable: status !== null,
    loading: false,
  }));
}

export function useAuthStatus(): AuthStatusState {
  const [state, setState] = useState<AuthStatusState>(INITIAL);

  useEffect(() => {
    let alive = true;
    loadAuthStatus().then((next) => {
      if (alive) setState(next);
    });
    return () => {
      alive = false;
    };
  }, []);

  return state;
}
