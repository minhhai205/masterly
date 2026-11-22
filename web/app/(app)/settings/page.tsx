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

/** Settings for the signed-in account: appearance and interface language. */
export default function SettingsPage() {
  const { t } = useTranslation();
  const { theme, setTheme, language, setLanguage } = useAppShell();

  return (
    <div className="h-full overflow-y-auto px-6 py-10 [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-2xl">
        <SettingsPageHeader
          title={t("Settings")}
          description={t("Your choices are saved to your account.")}
        />

        <SettingSection title={t("Appearance")}>
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
    </div>
  );
}
