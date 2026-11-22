/** Interface languages: Vietnamese (default) and English. Keys are the English text. */
export const APP_LANGUAGES = [
  { code: "vi", labelKey: "Vietnamese" },
  { code: "en", labelKey: "English" },
] as const;

export type AppLanguage = (typeof APP_LANGUAGES)[number]["code"];

export const DEFAULT_LANGUAGE: AppLanguage = "vi";

const SUPPORTED_CODES: ReadonlySet<string> = new Set(
  APP_LANGUAGES.map(({ code }) => code),
);

export function isAppLanguage(value: unknown): value is AppLanguage {
  return typeof value === "string" && SUPPORTED_CODES.has(value);
}

export function normalizeLanguage(value: unknown): AppLanguage {
  if (typeof value !== "string") return DEFAULT_LANGUAGE;
  const base = value.trim().toLowerCase().replaceAll("_", "-").split("-", 1)[0];
  if (base === "en") return "en";
  return DEFAULT_LANGUAGE;
}
