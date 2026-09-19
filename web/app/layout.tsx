import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Chetana AI — AIOps Console",
  description:
    "Alert, incident and automation console for the Chetana AI platform. Keep is the system of record.",
};

/**
 * Apply the stored theme before the first paint.
 *
 * Without this the page renders in the OS theme, then corrects itself once
 * React hydrates — a white flash on every navigation for anyone running the
 * console dark on a light desktop. It has to be inline and synchronous in the
 * head: a deferred script runs too late to prevent the flash it exists for.
 *
 * "system" deliberately stamps nothing, so the CSS media query decides. The
 * try/catch matters because localStorage throws outright in a private window,
 * and an exception here would block the page rather than the theme.
 */
const THEME_SCRIPT = `
(function () {
  try {
    var t = localStorage.getItem("chetana.theme");
    if (t === "dark" || t === "light") {
      document.documentElement.setAttribute("data-theme", t);
    }
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Linked rather than bundled with next/font: the Docker build would
            otherwise need to reach Google at build time, and a font is not
            worth a build that fails on a restricted network. If the request is
            blocked the stack falls back to the system sans and nothing breaks. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Geist:wght@400..700&family=Geist+Mono:wght@400..500&display=swap"
        />
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
