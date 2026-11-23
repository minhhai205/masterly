"use client";

import { notFound } from "next/navigation";

import { useSettingsAccess } from "@/features/settings/navigation/SettingsAccessProvider";
import { findSettingsPage } from "@/features/settings/navigation/settings-nav";
import AppearanceSettingsSection from "@/features/settings/sections/AppearanceSettingsSection";
import ConnectionsSettingsSection from "@/features/settings/sections/models/ConnectionsSettingsSection";
import EmbeddingSettingsSection from "@/features/settings/sections/models/EmbeddingSettingsSection";
import LlmSettingsSection from "@/features/settings/sections/models/LlmSettingsSection";
import SearchSettingsSection from "@/features/settings/sections/models/SearchSettingsSection";
import TaskModelsSettingsSection from "@/features/settings/sections/models/TaskModelsSettingsSection";

/** Each settings page key and the section that renders it. */
const SECTIONS: Record<string, React.ComponentType> = {
  appearance: AppearanceSettingsSection,
  connections: ConnectionsSettingsSection,
  llm: LlmSettingsSection,
  "task-models": TaskModelsSettingsSection,
  embedding: EmbeddingSettingsSection,
  search: SearchSettingsSection,
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
