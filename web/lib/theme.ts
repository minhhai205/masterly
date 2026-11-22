/**
 * Theme persistence: light or dark, kept in localStorage so the page paints in
 * the right theme before React loads (see ThemeScript), and saved per account
 * on the server through the interface settings.
 *
 * "light" uses the pure-white palette (CSS class `theme-snow`); "dark" uses the
 * `dark` class.
 */

import { browserStorage } from "@/shared/storage";

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "masterly-theme";

type ThemeChangeListener = (theme: Theme) => void;
const themeListeners = new Set<ThemeChangeListener>();

export function subscribeToThemeChanges(
  listener: ThemeChangeListener,
): () => void {
  themeListeners.add(listener);
  return () => themeListeners.delete(listener);
}

export function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark";
}

export function getStoredTheme(): Theme | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = browserStorage.readRaw("local", THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : null;
  } catch {
    return null; // localStorage may be disabled
  }
}

export function saveThemeToStorage(theme: Theme): boolean {
  if (typeof window === "undefined") return false;
  try {
    return browserStorage.writeRaw("local", THEME_STORAGE_KEY, theme);
  } catch {
    return false;
  }
}

/** The system preference, used until the person picks a theme. */
export function getSystemTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function applyThemeToDocument(theme: Theme): void {
  if (typeof document === "undefined") return;
  const html = document.documentElement;
  html.classList.remove("dark", "theme-snow");
  html.classList.add(theme === "dark" ? "dark" : "theme-snow");
}

/** Startup: stored choice first, then the system preference. */
export function initializeTheme(): Theme {
  const theme = getStoredTheme() ?? getSystemTheme();
  applyThemeToDocument(theme);
  saveThemeToStorage(theme);
  return theme;
}

export function setTheme(theme: Theme): void {
  applyThemeToDocument(theme);
  saveThemeToStorage(theme);
  themeListeners.forEach((listener) => listener(theme));
}
