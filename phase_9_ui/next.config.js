/** @type {import('next').NextConfig} */
const nextConfig = {
  // Full static export — no serverless functions at all. The app is a
  // client-side SPA that calls the Railway backend directly, so we don't
  // need any server-side rendering on Vercel. This bypasses Vercel's
  // serverless wrapper (which was crashing with FUNCTION_INVOCATION_FAILED)
  // and serves the site purely from Vercel's CDN.
  output: "export",
  images: { unoptimized: true },
};

module.exports = nextConfig;
