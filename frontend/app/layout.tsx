import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Aritiq — AI Financial Summary Auditor",
  description:
    "Aritiq traces every numeric claim in an AI-generated financial summary back to its source and re-checks the arithmetic deterministically.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`dark ${inter.variable} ${mono.variable}`}>
      <body>
        {/* Ambient atmosphere — purely behind content, disabled under reduced-motion */}
        <div aria-hidden className="ambient-blob animate-blob-drift" style={{ top: "-120px", left: "-80px", width: "420px", height: "420px", background: "#8B5CF6" }} />
        <div aria-hidden className="ambient-blob animate-blob-drift" style={{ bottom: "-160px", right: "-100px", width: "480px", height: "480px", background: "#F5A524", animationDelay: "-8s" }} />
        <div className="relative z-10">{children}</div>
      </body>
    </html>
  );
}
