import type { NextConfig } from "next";

const api = process.env.LINTEL_API_URL ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  // The browser only ever talks to this origin; /api is proxied to the FastAPI service so the
  // session cookie stays first-party.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/:path*` }];
  },
  poweredByHeader: false,
};

export default config;
