import { redirect } from "next/navigation";

import {
  DEFAULT_SETTINGS_PAGE,
  settingsPageHref,
} from "@/features/settings/navigation/settings-nav";

export default function SettingsEntry() {
  redirect(settingsPageHref(DEFAULT_SETTINGS_PAGE));
}
