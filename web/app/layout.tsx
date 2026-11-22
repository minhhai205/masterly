import type { Metadata } from "next";
import { Inter, Lora } from "next/font/google";
import "./globals.css";
import ThemeScript from "@/components/ThemeScript";
import { AppShellProvider } from "@/context/AppShellContext";
import { I18nClientBridge } from "@/i18n/I18nClientBridge";

// Both faces ship the Vietnamese subset, so diacritics render in the same font.
const fontSans = Inter({
  subsets: ["latin", "vietnamese"],
  display: "swap",
  variable: "--font-sans",
});

const fontSerif = Lora({
  subsets: ["latin", "vietnamese"],
  display: "swap",
  variable: "--font-serif",
});

export const metadata: Metadata = {
  title: "Masterly",
  description: "Không gian học tập AI cá nhân hóa, thích ứng theo tiến trình người học",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="vi"
      suppressHydrationWarning
      data-scroll-behavior="smooth"
      className={`${fontSans.variable} ${fontSerif.variable}`}
    >
      <head>
        <ThemeScript />
      </head>
      <body
        className="font-sans bg-[var(--background)] text-[var(--foreground)]"
        suppressHydrationWarning
      >
        <AppShellProvider>
          <I18nClientBridge>{children}</I18nClientBridge>
        </AppShellProvider>
      </body>
    </html>
  );
}
