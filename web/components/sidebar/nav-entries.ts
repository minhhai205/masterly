import { House, Settings, type LucideIcon } from "lucide-react";

export interface NavEntry {
  href: string;
  /** English text, also the translation key. */
  label: string;
  icon: LucideIcon;
}

/**
 * Main entries, in order. Each feature adds its own entry when it is built
 * (chat with F04, learning paths with F08).
 */
export const PRIMARY_NAV: NavEntry[] = [{ href: "/", label: "Home", icon: House }];

/** Entries pinned to the bottom of the sidebar. */
export const SECONDARY_NAV: NavEntry[] = [
  { href: "/settings", label: "Settings", icon: Settings },
];

export function isNavActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
