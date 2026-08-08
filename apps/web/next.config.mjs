/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Static export for Cloudflare Pages
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};
export default nextConfig;