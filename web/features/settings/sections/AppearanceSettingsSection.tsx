"use client";

import { useTranslation } from "react-i18next";

import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
  nativeSelectClass,
} from "@/components/settings/shared";
import { ThemePreviewCard } from "@/components/settings/ThemePreviewCard";
import { useAppShell } from "@/context/AppShellContext";
import { APP_LANGUAGES, isAppLanguage } from "@/i18n/languages";
import type { Theme } from "@/lib/theme";

const THEMES: { id: Theme; label: string }[] = [
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
];

/**
 * Theme and interface language of the signed-in account. These apply at once
 * and are saved to the account; they are not part of the model-settings draft.
 */
export default function AppearanceSettingsSection() {
  const { t } = useTranslation();
  const { theme, setTheme, language, setLanguage } = useAppShell();

  return (
    <div>
      <SettingsPageHeader
        title={t("Appearance")}
        description={t("Your choices are saved to your account.")}
      />

      <SettingSection title={t("Theme")}>
        <div className="grid grid-cols-2 gap-3 py-4 sm:max-w-md">
          {THEMES.map(({ id, label }) => (
            <ThemePreviewCard
              key={id}
              theme={id}
              label={t(label)}
              selected={theme === id}
              onSelect={setTheme}
            />
          ))}
        </div>
      </SettingSection>

      <SettingSection title={t("Language")}>
        <SettingRow
          title={t("Interface language")}
          description={t("Language of menus, buttons and messages.")}
          control={
            <select
              value={language}
              onChange={(event) => {
                if (isAppLanguage(event.target.value)) {
                  setLanguage(event.target.value);
                }
              }}
              className={nativeSelectClass}
              aria-label={t("Interface language")}
            >
              {APP_LANGUAGES.map(({ code, labelKey }) => (
                <option key={code} value={code}>
                  {t(labelKey)}
                </option>
              ))}
            </select>
          }
        />
      </SettingSection>
    </div>
  );
}
