import { type NextRequest } from 'next/server'

/**
 * The BFF proxy.
 *
 * The API is deployed on a different domain from this app, so the browser
 * never calls it directly: it would be a cross-site cookie, and Safari blocks
 * those unconditionally while Chrome restricts them — a ward on iPads would
 * simply keep getting logged out. Instead the browser only ever talks to this
 * origin, this handler forwards server-side, and Django's Set-Cookie is
 * re-issued here with its Domain attribute stripped so the session lands as a
 * first-party, HttpOnly cookie on *this* host.
 *
 * That is also why there is no token in localStorage: with patient records, a
 * credential readable by JavaScript is an XSS payoff not worth taking.
 */
const DJANGO_ORIGIN = process.env.DJANGO_ORIGIN ?? 'http://127.0.0.1:8009'

// Hop-by-hop and length headers must not be forwarded; the fetch layer sets
// its own, and forwarding a stale content-length truncates request bodies.
const STRIPPED_REQUEST_HEADERS = new Set([
  'host', 'connection', 'keep-alive', 'transfer-encoding', 'upgrade',
  'proxy-authorization', 'proxy-authenticate', 'te', 'trailer',
  'content-length', 'accept-encoding',
])

const STRIPPED_RESPONSE_HEADERS = new Set([
  'connection', 'keep-alive', 'transfer-encoding', 'upgrade',
  'content-encoding', 'content-length',
])

/**
 * Drop `Domain=` so the cookie is scoped to this host, and drop `Secure` when
 * this app is itself being served over plain HTTP in development — otherwise
 * the browser silently discards the session cookie and login appears to
 * succeed while every subsequent request is anonymous.
 */
function rebindCookieToThisHost(setCookie: string, isSecureRequest: boolean) {
  const parts = setCookie.split(';').filter((part) => {
    const name = part.trim().toLowerCase()
    if (name.startsWith('domain=')) return false
    if (name === 'secure' && !isSecureRequest) return false
    return true
  })
  return parts.join(';')
}

async function proxy(request: NextRequest) {
  // Taken from the pathname rather than the matched segments, so the trailing
  // slash Django insists on survives verbatim.
  const path = request.nextUrl.pathname.replace(/^\/api/, '')
  const target = `${DJANGO_ORIGIN}/api${path}${request.nextUrl.search}`

  const headers = new Headers()
  request.headers.forEach((value, key) => {
    if (!STRIPPED_REQUEST_HEADERS.has(key.toLowerCase())) headers.set(key, value)
  })
  // Django validates CSRF against the origin it is told about, so it must be
  // this app's origin — which is what CSRF_TRUSTED_ORIGINS lists.
  headers.set('x-forwarded-host', request.nextUrl.host)
  headers.set('x-forwarded-proto', request.nextUrl.protocol.replace(':', ''))

  const hasBody = !['GET', 'HEAD'].includes(request.method)
  let upstream: Response
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: 'manual',
      cache: 'no-store',
    })
  } catch {
    // The API being unreachable is an operational fact staff need stated
    // plainly, not a blank screen.
    return Response.json(
      { detail: 'The hospital server is not reachable. Check the connection to it, then try again.' },
      { status: 503 },
    )
  }

  const responseHeaders = new Headers()
  upstream.headers.forEach((value, key) => {
    if (!STRIPPED_RESPONSE_HEADERS.has(key.toLowerCase()) && key.toLowerCase() !== 'set-cookie') {
      responseHeaders.set(key, value)
    }
  })

  const isSecureRequest = request.nextUrl.protocol === 'https:'
  for (const cookie of upstream.headers.getSetCookie()) {
    responseHeaders.append('set-cookie', rebindCookieToThisHost(cookie, isSecureRequest))
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  })
}

export const GET = proxy
export const POST = proxy
export const PATCH = proxy
export const PUT = proxy
export const DELETE = proxy
