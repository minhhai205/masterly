import type { AuthStatus } from "@/lib/auth";

export interface SettingsAccess {
  /** False until the backend has resolved the signed-in account. */
  resolved: boolean;
  /** Administrator-only pages (models and services) stay hidden for learners. */
  hideAdminOnly: boolean;
}

export const PENDING_SETTINGS_ACCESS: SettingsAccess = {
  resolved: false,
  hideAdminOnly: true,
};

/** Convert the backend's account identity into the settings visibility model. */
export function settingsAccessFromAuthStatus(
  authStatus: AuthStatus | null,
): SettingsAccess {
  return { resolved: true, hideAdminOnly: !authStatus?.is_admin };
}
