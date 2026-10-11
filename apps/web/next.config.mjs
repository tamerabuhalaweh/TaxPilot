/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true
  // API proxying is handled at request time by app/api/v1/[...path]/route.ts
  // (runtime API_INTERNAL_URL), not by build-time rewrites.
};

export default nextConfig;
