/** Account roles: the group owner, and the learners the owner created. */
export type AccountRole = "owner" | "learner";

const LABEL_KEYS: Record<AccountRole, string> = {
  owner: "Group owner",
  learner: "Learner",
};

export function accountRoleLabelKey(role: AccountRole | string): string {
  return LABEL_KEYS[role as AccountRole] ?? "Learner";
}
