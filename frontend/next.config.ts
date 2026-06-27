import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // 개발환경에서 /api/* → FastAPI 백엔드로 프록시 (CORS 우회)
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_BASE ?? "http://localhost:8000"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
