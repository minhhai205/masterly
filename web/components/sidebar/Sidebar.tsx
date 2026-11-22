"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTranslation } from "react-i18next";

import { BrandMark } from "@/components/brand/BrandMark";
import { LogoutButton } from "@/components/auth/LogoutButton";
import { ProfileLink } from "@/components/auth/ProfileLink";
import { useSidebarDrawer } from "@/components/layout/AppShell";
import { useAppShell } from "@/context/AppShellContext";
import Tooltip from "@/shared/ui/Tooltip";
import {
  PRIMARY_NAV,
  SECONDARY_NAV,
  isNavActive,
  type NavEntry,
} from "./nav-entries";

function NavLink({
  item,
  active,
  collapsed,
  onNavigate,
}: {
  item: NavEntry;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const { t } = useTranslation();
  const label = t(item.label);
  const link = (
    <Link
      href={item.href}
      prefetch={false}
      onClick={onNavigate}
      aria-label={collapsed ? label : undefined}
      className={`flex min-h-8 items-center gap-2.5 rounded-md text-[13.5px] transition-colors ${
        collapsed ? "justify-center p-2" : "px-2.5 py-1.5"
      } ${
        active
          ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
          : "text-foreground/85 hover:bg-background/60 hover:text-[var(--foreground)]"
      }`}
    >
      <item.icon size={16} strokeWidth={active ? 1.9 : 1.6} />
      {collapsed ? null : <span className="truncate">{label}</span>}
    </Link>
  );
  return collapsed ? (
    <Tooltip label={label} side="right">
      {link}
    </Tooltip>
  ) : (
    link
  );
}

/**
 * The app sidebar: brand, main entries, and a footer with the profile, sign-out
 * and settings. On desktop it collapses to a rail; on phones AppShell shows it
 * as a drawer.
 */
export default function Sidebar() {
  const { t } = useTranslation();
  const pathname = usePathname();
  const drawer = useSidebarDrawer();
  const { sidebarCollapsed, setSidebarCollapsed } = useAppShell();
  const closeDrawer = () => drawer?.close();

  if (sidebarCollapsed) {
    return (
      <aside className="flex h-dvh w-[56px] shrink-0 flex-col items-center bg-[var(--secondary)] py-3 max-md:hidden">
        <BrandMark compact />
        <button
          onClick={() => setSidebarCollapsed(false)}
          className="mt-3 rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          aria-label={t("Expand sidebar")}
        >
          <PanelLeftOpen size={15} />
        </button>
        <nav className="mt-3 flex flex-col gap-1">
          {PRIMARY_NAV.map((item) => (
            <NavLink
              key={item.href}
              item={item}
              active={isNavActive(pathname, item.href)}
              collapsed
            />
          ))}
        </nav>
        <div className="mt-auto flex flex-col items-center gap-1">
          {SECONDARY_NAV.map((item) => (
            <NavLink
              key={item.href}
              item={item}
              active={isNavActive(pathname, item.href)}
              collapsed
            />
          ))}
          <ProfileLink collapsed />
          <LogoutButton collapsed />
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex h-dvh w-[232px] shrink-0 flex-col bg-[var(--secondary)] max-md:w-[220px] max-md:max-w-[85vw]">
      <div className="flex h-[52px] shrink-0 items-center justify-between px-4">
        <BrandMark />
        <button
          onClick={() => setSidebarCollapsed(true)}
          className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] max-md:hidden"
          aria-label={t("Collapse sidebar")}
        >
          <PanelLeftClose size={15} />
        </button>
      </div>

      <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
        {PRIMARY_NAV.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            active={isNavActive(pathname, item.href)}
            collapsed={false}
            onNavigate={closeDrawer}
          />
        ))}
      </nav>

      <div className="shrink-0 space-y-0.5 border-t border-border/40 px-2 py-2">
        {SECONDARY_NAV.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            active={isNavActive(pathname, item.href)}
            collapsed={false}
            onNavigate={closeDrawer}
          />
        ))}
        <ProfileLink />
        <LogoutButton />
      </div>
    </aside>
  );
}
