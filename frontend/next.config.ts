import type { NextConfig } from 'next'

const config: NextConfig = {
  reactStrictMode: true,
  // The API is reached through src/app/api/[...path]/route.ts, not a rewrite:
  // a rewrite cannot re-issue Django's Set-Cookie on this host, which is the
  // whole point of proxying (see the route handler).
  poweredByHeader: false,
  // Django's URLs end in a slash and APPEND_SLASH cannot help a proxied POST
  // (it would 301 and drop the body). Without this, Next 308-redirects
  // /api/auth/login/ to /api/auth/login before the handler ever runs.
  skipTrailingSlashRedirect: true,
}

export default config
