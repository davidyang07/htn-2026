import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppShell } from "@/components/shell/AppShell";
import { ExperimentProvider } from "@/lib/experiment/ExperimentProvider";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AgentShield — Multi-Agent Adversarial Resilience",
  description:
    "Map agent systems, run adversarial scenarios, watch compromise propagate, compare defenses, trace causality, and validate remediation.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      {/* Browser extensions routinely add attributes to <body> before React
          hydrates; without this every page logs a hydration mismatch that has
          nothing to do with this app. */}
      <body className="h-full" suppressHydrationWarning>
        {/* The provider sits above the shell so the live WebSocket, and the
            run it is watching, survive navigation between every screen. */}
        <ExperimentProvider>
          <AppShell>{children}</AppShell>
        </ExperimentProvider>
      </body>
    </html>
  );
}
