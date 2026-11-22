"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { apiFetch, apiUrl } from "@/lib/api";
import {
  getStoredTheme,
  getSystemTheme,
  isTheme,
  setTheme as applyTheme,
  subscribeToThemeChanges,
  type Theme,
} from "@/lib/theme";
import {
  DEFAULT_LANGUAGE,
  isAppLanguage,
  normalizeLanguage,
  type AppLanguage,
} from "@/i18n/languages";
import { browserStorage } from "@/shared/storage";

export const LANGUAGE_STORAGE_KEY = "masterly-language";
export const SIDEBAR_COLLAPSED_STORAGE_KEY = "masterly.sidebarCollapsed";

interface AppShellContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  language: AppLanguage;
  /** False until the saved language is known, so pages never flash in the wrong one. */
  languageReady: boolean;
  setLanguage: (language: AppLanguage) => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
}

const AppShellContext = createContext<AppShellContextValue | null>(null);

function readStoredLanguage(): AppLanguage | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = browserStorage.readRaw("local", LANGUAGE_STORAGE_KEY);
    return isAppLanguage(raw) ? raw : null;
  } catch {
    return null;
  }
}

function writeStoredLanguage(language: AppLanguage): void {
  try {
    browserStorage.writeRaw("local", LANGUAGE_STORAGE_KEY, language);
  } catch {
    // localStorage may be disabled: the choice still applies to this page.
  }
}

/** Save a preference to the signed-in account; ignored when signed out. */
function saveUiSetting(patch: { theme?: Theme; language?: AppLanguage }): void {
  void apiFetch(apiUrl("/api/settings/ui"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
    skipAuthRedirect: true,
  }).catch(() => undefined);
}

export function AppShellProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(
    () => getStoredTheme() ?? getSystemTheme(),
  );
  // Start with the default to match server rendering, then hydrate.
  const [language, setLanguageState] = useState<AppLanguage>(DEFAULT_LANGUAGE);
  const [languageReady, setLanguageReady] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsedState] = useState(false);

  useEffect(() => {
    // Client-only preference, read after the server-matching first render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSidebarCollapsedState(
      browserStorage.readRaw("local", SIDEBAR_COLLAPSED_STORAGE_KEY) === "1",
    );
  }, []);

  useEffect(() => {
    // A choice made in this browser wins. Without one, adopt what the account
    // saved on the server (or the deployment default on the sign-in page).
    const stored = readStoredLanguage();
    if (stored) {
      // Same reason: localStorage is only readable after the first render.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLanguageState(stored);
      setLanguageReady(true);
      return;
    }
    const controller = new AbortController();
    const fallback = setTimeout(() => {
      controller.abort();
      setLanguageReady(true);
    }, 1_500);
    void (async () => {
      try {
        const response = await apiFetch(apiUrl("/api/settings/ui"), {
          signal: controller.signal,
          skipAuthRedirect: true,
        });
        if (!response.ok) return;
        const payload = (await response.json()) as {
          theme?: unknown;
          language?: unknown;
        };
        if (isAppLanguage(payload.language)) {
          writeStoredLanguage(payload.language);
          setLanguageState(payload.language);
        }
        if (isTheme(payload.theme) && !getStoredTheme()) {
          applyTheme(payload.theme);
        }
      } catch {
        // Offline: keep the default.
      } finally {
        clearTimeout(fallback);
        setLanguageReady(true);
      }
    })();
    return () => {
      clearTimeout(fallback);
      controller.abort();
    };
  }, []);

  useEffect(() => subscribeToThemeChanges(setThemeState), []);

  useEffect(() => {
    // Keep several open tabs in step.
    const onStorage = (event: StorageEvent) => {
      if (event.key === LANGUAGE_STORAGE_KEY) {
        setLanguageState(normalizeLanguage(event.newValue));
      }
      if (event.key === SIDEBAR_COLLAPSED_STORAGE_KEY) {
        setSidebarCollapsedState(event.newValue === "1");
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setTheme = useCallback((next: Theme) => {
    applyTheme(next);
    saveUiSetting({ theme: next });
  }, []);

  const setLanguage = useCallback((next: AppLanguage) => {
    writeStoredLanguage(next);
    setLanguageState(next);
    saveUiSetting({ language: next });
  }, []);

  const setSidebarCollapsed = useCallback((collapsed: boolean) => {
    setSidebarCollapsedState(collapsed);
    try {
      browserStorage.writeRaw(
        "local",
        SIDEBAR_COLLAPSED_STORAGE_KEY,
        collapsed ? "1" : "0",
      );
    } catch {
      // ignore
    }
  }, []);

  const value = useMemo(
    () => ({
      theme,
      setTheme,
      language,
      languageReady,
      setLanguage,
      sidebarCollapsed,
      setSidebarCollapsed,
    }),
    [
      theme,
      setTheme,
      language,
      languageReady,
      setLanguage,
      sidebarCollapsed,
      setSidebarCollapsed,
    ],
  );

  return (
    <AppShellContext.Provider value={value}>{children}</AppShellContext.Provider>
  );
}

export function useAppShell(): AppShellContextValue {
  const context = useContext(AppShellContext);
  if (!context) {
    throw new Error("useAppShell must be used inside AppShellProvider");
  }
  return context;
}
