/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
};

// next-pwa is optional — skip if not installed
try {
  const withPWA = require("next-pwa")({
    dest: "public",
    disable: process.env.NODE_ENV === "development",
    register: true,
    skipWaiting: true,
  });
  module.exports = withPWA(nextConfig);
} catch {
  module.exports = nextConfig;
}
