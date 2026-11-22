/** Account roles: one administrator, everyone else a learner. */
export type AccountRole = "admin" | "user";

const LABEL_KEYS: Record<AccountRole, string> = {
  admin: "Administrator",
  user: "Learner",
};

export function accountRoleLabelKey(role: AccountRole | string): string {
  return LABEL_KEYS[role as AccountRole] ?? "Learner";
}
