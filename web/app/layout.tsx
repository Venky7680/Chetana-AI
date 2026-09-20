import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Chetana AI — AIOps Console",
  description:
    "Alert, incident and automation console for the Chetana AI platform. Keep is the system of record.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // The console is dark only, matching the marketing site, so the theme is
    // stamped here rather than decided at runtime. That removes the inline
    // no-flash script this file used to carry: with one theme there is no
    // stored preference to read and nothing to flash between.
    <html lang="en" data-theme="dark">
      <head>
        {/* The two faces the first paint needs. Everything else about the
            fonts — the @font-face rules, the subsets — is in globals.css;
            these preloads exist so the text is not briefly set in the
            fallback on a cold load. They are same-origin: nothing about this
            page reaches a third party. */}
        <link
          rel="preload"
          as="font"
          type="font/woff2"
          href="/fonts/inter-latin-400.woff2"
          crossOrigin="anonymous"
        />
        <link
          rel="preload"
          as="font"
          type="font/woff2"
          href="/fonts/inter-latin-500.woff2"
          crossOrigin="anonymous"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
