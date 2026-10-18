import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import { zonesFile } from "@/lib/zones";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const DESCRIPTION =
  "Walk through an unofficial, fan-made 3D model of Vantara, Jamnagar: elephant shelters and pools, the wildlife hospital, big-cat enclosures and herbivore paddocks. An artistic interpretation built from open map data.";

export const metadata: Metadata = {
  title: { default: "Vantara 3D", template: "%s · Vantara 3D" },
  description: DESCRIPTION,
  applicationName: "Vantara 3D",
  openGraph: { title: "Vantara 3D", description: DESCRIPTION, type: "website", siteName: "Vantara 3D" },
  twitter: { card: "summary", title: "Vantara 3D", description: DESCRIPTION },
};

export const viewport: Viewport = {
  themeColor: "#0b0f0b",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {children}
        <footer className="flex h-12 shrink-0 items-center gap-x-4 overflow-hidden border-t border-neutral-500/20 px-4 text-xs leading-tight text-neutral-500">
          <span className="min-w-0 truncate">{zonesFile.site.disclaimer}</span>
          <span className="ml-auto hidden shrink-0 sm:inline">
            Map data ©{" "}
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" className="underline">
              OpenStreetMap contributors
            </a>
          </span>
          <Link href="/credits" className="shrink-0 underline max-sm:ml-auto">
            Credits
          </Link>
        </footer>
      </body>
    </html>
  );
}
