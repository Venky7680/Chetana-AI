/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Produces .next/standalone for the container image.
  output: "standalone",
  env: {
    // Point the browser at the BFF. In Docker Compose this is the published
    // port on the host, not the service name.
    NEXT_PUBLIC_BFF_URL: process.env.NEXT_PUBLIC_BFF_URL ?? "http://localhost:8080",
  },

  /**
   * Serve the marketing landing page at the root.
   *
   * The landing page is a prebuilt Vite bundle living in public/ — it is not a
   * Next route and is deliberately not ported into this app, so that what ships
   * is byte-for-byte the page that was designed rather than a reimplementation
   * of it that drifts.
   *
   * `beforeFiles` matters. A plain rewrites array runs *after* filesystem
   * routes, so the console page would win at "/" and the landing page would
   * never be reached. beforeFiles runs first and shadows it.
   *
   * Everything the bundle requests — /assets/*, /story/*, /logos/*, the hero
   * images — is served straight out of public/ at those exact paths, which is
   * what the build expects: Vite emitted absolute URLs for them, so they must
   * sit at the domain root and cannot be nested under a prefix.
   */
  async rewrites() {
    return {
      beforeFiles: [{ source: "/", destination: "/index.html" }],
      afterFiles: [],
      fallback: [],
    };
  },
};

export default nextConfig;
