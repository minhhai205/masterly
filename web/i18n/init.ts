import i18n, { type Resource } from "i18next";
import { initReactI18next } from "react-i18next";

import enApp from "@/locales/en/app.json";
import viApp from "@/locales/vi/app.json";
import { normalizeLanguage, type AppLanguage } from "./languages";

export { APP_LANGUAGES, isAppLanguage, normalizeLanguage } from "./languages";
export type { AppLanguage } from "./languages";

let _initialized = false;

/**
 * Keys are the English text itself (`t("Sign in")`), so English needs no
 * bundle entry for most strings and a missing Vietnamese entry falls back to
 * English instead of showing a key.
 */
export function initI18n(language?: unknown) {
  if (_initialized) return i18n;
  const resources: Resource = {
    en: { app: enApp },
    vi: { app: viApp },
  };
  i18n.use(initReactI18next).init({
    resources,
    lng: normalizeLanguage(language),
    fallbackLng: "en",
    defaultNS: "app",
    ns: ["app"],
    // Keys contain dots and colons ("Saving…", "Joined: {{date}}").
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
    returnEmptyString: false,
    returnNull: false,
  });
  _initialized = true;
  return i18n;
}

/** Both bundles ship with the app, so there is nothing to load on demand. */
export async function ensureLanguage(_language: AppLanguage) {}
