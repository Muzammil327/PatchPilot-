import type { NextConfig } from "next";

// Optional: when set (e.g. on Vercel), /api/* is forwarded to this backend so the browser
// sees one site and the session cookie stays first-party. Unset locally, where the
// frontend calls NEXT_PUBLIC_API_BASE_URL directly.
const BACKEND_URL = (process.env.BACKEND_URL ?? "").trim().replace(/\/$/, "");

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,
  // The signed-in user's GitHub avatar in the workspace sidebar.
  images: {
    remotePatterns: [{ protocol: "https", hostname: "avatars.githubusercontent.com", pathname: "/**" }],
  },
  async rewrites() {
    if (!BACKEND_URL) return [];
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
