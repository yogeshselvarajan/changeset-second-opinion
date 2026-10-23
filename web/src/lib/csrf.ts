/** CSRF double-submit: the readable `cso_csrf` cookie is echoed in the `X-CSRF` header. */
export const CSRF_COOKIE = "cso_csrf";
export const CSRF_HEADER = "X-CSRF";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function isSafeMethod(method: string): boolean {
  return SAFE_METHODS.has(method.toUpperCase());
}

/** Read one cookie from a `document.cookie` style string; undefined when absent. */
export function readCookie(name: string, cookieString: string): string | undefined {
  for (const part of cookieString.split(";")) {
    const index = part.indexOf("=");
    if (index === -1) continue;
    if (part.slice(0, index).trim() !== name) continue;
    const raw = part.slice(index + 1).trim();
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  }
  return undefined;
}

/**
 * Add the CSRF header to a mutating request when the cookie exists.
 * Safe methods are left alone; a request without the cookie is sent as is (the server answers 403).
 */
export function withCsrf(request: Request, cookieString: string): Request {
  if (isSafeMethod(request.method)) return request;
  const token = readCookie(CSRF_COOKIE, cookieString);
  if (token) request.headers.set(CSRF_HEADER, token);
  return request;
}
