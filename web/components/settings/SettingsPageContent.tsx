"use client";

import { notFound } from "next/navigation";

import { useSettingsAccess } from "@/features/settings/navigation/SettingsAccessProvider";
import { findSettingsPage } from "@/features/settings/navigation/settings-nav";
import AppearanceSettingsSection from "@/features/settings/sections/AppearanceSettingsSection";

/** Each settings page key and the section that renders it. */
const SECTIONS: Record<string, React.ComponentType> = {
  appearance: AppearanceSettingsSection,
};

export default function SettingsPageContent({ section }: { section: string }) {
  const access = useSettingsAccess();
  const page = findSettingsPage(section);
  const Section = SECTIONS[section];
  if (!page || !Section) notFound();
  // Wait for the account before deciding on an administrator-only page.
  if (page.adminOnly && !access.resolved) return null;
  if (page.adminOnly && access.hideAdminOnly) notFound();
  return <Section />;
}
