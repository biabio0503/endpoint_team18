/** @type {import('next').NextConfig} */
const apiOrigin = process.env.ROADMAP_API_ORIGIN || 'http://127.0.0.1:8000';
const config = {
  experimental: { middlewareClientMaxBodySize: Number(process.env.ROADMAP_PROXY_MAX_BODY_BYTES || 11534336) },
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${apiOrigin}/api/:path*` }];
  },
};
export default config;
