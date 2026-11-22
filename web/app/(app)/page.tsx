"use client";

import { useTranslation } from "react-i18next";

import { useAuthStatus } from "@/hooks/useAuthStatus";

/**
 * Home. For now a welcome page; chat (F04) and learning paths (F08) take over
 * this space as they are built.
 */
export default function HomePage() {
  const { t } = useTranslation();
  const { loading } = useAuthStatus();

  return (
    <div className="flex h-full items-center justify-center px-6">
      <div className="max-w-md text-center">
        <h1 className="font-serif text-2xl font-semibold tracking-tight text-[var(--foreground)]">
          {t("Welcome to Masterly")}
        </h1>
        <p className="mt-2 text-sm text-[var(--muted-foreground)]">
          {loading ? "" : t("Learn by goal, master each point, review on time.")}
        </p>
      </div>
    </div>
  );
}
