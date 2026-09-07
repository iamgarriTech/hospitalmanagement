import type { NextConfig } from 'next'

const config: NextConfig = {
  reactStrictMode: true,
  // The API is reached through src/app/api/[...path]/route.ts, not a rewrite:
  // a rewrite cannot re-issue Django's Set-Cookie on this host, which is the
  // whole point of proxying (see the route handler).
  poweredByHeader: false,
}

export default config
