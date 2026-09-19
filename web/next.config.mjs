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
};

export default nextConfig;
