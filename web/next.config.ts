import type { NextConfig } from "next";

// Static export: `npm run build` -> web/out, served by `ezra-udp serve` on :8765.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  devIndicators: false,
};

export default nextConfig;
