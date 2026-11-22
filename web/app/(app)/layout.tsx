import AppShell from "@/components/layout/AppShell";
import Sidebar from "@/components/sidebar/Sidebar";

/** Every signed-in page: the sidebar plus the page content. */
export default function AppLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return <AppShell sidebar={<Sidebar />}>{children}</AppShell>;
}
