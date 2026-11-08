/** @type {import('next').NextConfig} */
const configuredOrigin = process.env.ROADMAP_API_ORIGIN;
if (process.env.NODE_ENV === 'production' && !configuredOrigin) {
  throw new Error('ROADMAP_API_ORIGIN must be set for production builds.');
}
const apiOrigin = configuredOrigin || 'http://127.0.0.1:8000';
let parsedOrigin;
try {
  parsedOrigin = new URL(apiOrigin);
} catch {
  throw new Error('ROADMAP_API_ORIGIN must be an absolute HTTP(S) origin.');
}
if (!['http:', 'https:'].includes(parsedOrigin.protocol) || parsedOrigin.username || parsedOrigin.password || parsedOrigin.pathname !== '/' || parsedOrigin.search || parsedOrigin.hash ||
    (process.env.NODE_ENV === 'production' && (parsedOrigin.protocol !== 'https:' || ['localhost', '127.0.0.1', '[::1]'].includes(parsedOrigin.hostname)))) {
  throw new Error('ROADMAP_API_ORIGIN must be a valid HTTPS origin in production.');
}
const config = {
  experimental: { middlewareClientMaxBodySize: Number(process.env.ROADMAP_PROXY_MAX_BODY_BYTES || 11534336) },
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${parsedOrigin.origin}/api/:path*` }];
  },
};
export default config;
