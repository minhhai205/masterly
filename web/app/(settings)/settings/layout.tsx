import SettingsMain from "@/components/settings/SettingsMain";
import { SettingsAccessProvider } from "@/features/settings/navigation/SettingsAccessProvider";
import {
  ModelCatalogProvider,
  SettingsDraftProvider,
  SettingsProvider,
} from "@/features/settings/store";

/** Settings owns its navigation, independently of the app sidebar. */
export default function SettingsLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <SettingsProvider>
      <SettingsAccessProvider>
        <ModelCatalogProvider>
          <SettingsDraftProvider>
            <SettingsMain>{children}</SettingsMain>
          </SettingsDraftProvider>
        </ModelCatalogProvider>
      </SettingsAccessProvider>
    </SettingsProvider>
  );
}
