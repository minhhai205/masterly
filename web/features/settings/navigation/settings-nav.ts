import { Palette, type LucideIcon } from "lucide-react";

import type { SettingsAccess } from "@/features/settings/navigation/settings-access";

/**
 * Settings information architecture: groups of independent pages under
 * `/settings/<key>`. Labels and blurbs are English and double as i18n keys.
 * Each function adds its own pages when it is built.
 */
export interface SettingsPage {
  key: string;
  label: string;
  blurb: string;
  icon: LucideIcon;
  /** Hidden from learners (the backend refuses them anyway). */
  adminOnly?: boolean;
}

export interface SettingsPageGroup {
  label: string;
  pages: SettingsPage[];
}

export const SETTINGS_HUB_HREF = "/settings";
export const DEFAULT_SETTINGS_PAGE = "appearance";

export const SETTINGS_PAGE_GROUPS: SettingsPageGroup[] = [
  {
    label: "Personal",
    pages: [
      {
        key: "appearance",
        label: "Appearance",
        blurb: "Theme and interface language",
        icon: Palette,
      },
    ],
  },
];

/** Master–detail pages (a list beside an editor) need the wider content box. */
const WIDE_SETTINGS_PAGES = new Set<string>();

export function isWideSettingsPage(key: string): boolean {
  return WIDE_SETTINGS_PAGES.has(key);
}

export function settingsPageHref(key: string): string {
  return `${SETTINGS_HUB_HREF}/${key}`;
}

export function visibleSettingsGroups(access: SettingsAccess): SettingsPageGroup[] {
  return SETTINGS_PAGE_GROUPS.map((group) => ({
    ...group,
    pages: group.pages.filter((page) => !(page.adminOnly && access.hideAdminOnly)),
  })).filter((group) => group.pages.length > 0);
}

export function findSettingsPage(key: string): SettingsPage | null {
  for (const group of SETTINGS_PAGE_GROUPS) {
    const page = group.pages.find((item) => item.key === key);
    if (page) return page;
  }
  return null;
}
