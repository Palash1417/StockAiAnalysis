import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MF FAQ Assistant",
  description: "Facts-only assistant for mutual fund scheme queries.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full dark">
      <body className="h-full bg-surface-base text-ink-primary antialiased font-sans">
        {children}
      </body>
    </html>
  );
}
