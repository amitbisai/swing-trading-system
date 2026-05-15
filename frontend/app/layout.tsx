import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import { Nav } from "@/components/nav";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "SwingTrader",
  description: "AI-powered swing trading suggestions — 3–14 day positions",
  manifest: "/manifest.json",
};

export const viewport: Viewport = {
  themeColor: "#0f172a",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={inter.className}>
        <Nav />
        {/* main content — padded away from mobile bottom tab bar */}
        <main className="pb-20 sm:pb-0 min-h-screen">
          {children}
        </main>
      </body>
    </html>
  );
}
