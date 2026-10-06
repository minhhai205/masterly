import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Masterly",
  description: "Không gian học tập AI cá nhân hóa",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body className="min-h-screen bg-white text-gray-900 antialiased">{children}</body>
    </html>
  );
}
