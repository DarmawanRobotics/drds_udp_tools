import type { NextConfig } from "next";

// Static export: `npm run build` -> web/out, served by `ezra-udp serve` on :8765.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  devIndicators: false,
  // pin the root to web/ so lockfiles in parent folders (e.g. ~/pnpm-lock.yaml) are not considered
  turbopack: { root: __dirname },
};

export default nextConfig;
