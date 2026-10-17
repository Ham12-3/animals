import type { Metadata } from "next";
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

export const metadata: Metadata = {
  title: "Vantara 3D",
  description: "Unofficial fan reconstruction of Vantara, Jamnagar, as walkable Gaussian splats.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {children}
        <footer className="flex h-12 shrink-0 items-center border-t border-neutral-500/20 px-4 text-xs leading-tight text-neutral-500">
          {zonesFile.site.disclaimer}
        </footer>
      </body>
    </html>
  );
}
