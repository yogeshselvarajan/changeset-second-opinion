import { describe, expect, it } from "vitest";

import { CSRF_HEADER, isSafeMethod, readCookie, withCsrf } from "./csrf";

const cookies = "theme=dark; cso_csrf=abc%20123; other=x";

describe("readCookie", () => {
  it("finds a cookie and decodes it", () => {
    expect(readCookie("cso_csrf", cookies)).toBe("abc 123");
  });

  it("returns undefined for a missing cookie or an empty string", () => {
    expect(readCookie("nope", cookies)).toBeUndefined();
    expect(readCookie("cso_csrf", "")).toBeUndefined();
  });

  it("does not match a cookie whose name only ends the same way", () => {
    expect(readCookie("csrf", "xcsrf=1")).toBeUndefined();
  });

  it("keeps a malformed escape as is instead of throwing", () => {
    expect(readCookie("cso_csrf", "cso_csrf=%E0%A4%A")).toBe("%E0%A4%A");
  });
});

describe("withCsrf", () => {
  const url = "http://localhost/api/v1/cases";

  it("adds the header to mutating requests", () => {
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
      const request = withCsrf(new Request(url, { method }), "cso_csrf=tok");
      expect(request.headers.get(CSRF_HEADER)).toBe("tok");
    }
  });

  it("leaves safe methods alone", () => {
    for (const method of ["GET", "HEAD", "OPTIONS"]) {
      const request = withCsrf(new Request(url, { method }), "cso_csrf=tok");
      expect(request.headers.has(CSRF_HEADER)).toBe(false);
    }
  });

  it("sends no header when the cookie is absent (the server answers 403)", () => {
    const request = withCsrf(new Request(url, { method: "POST" }), "theme=dark");
    expect(request.headers.has(CSRF_HEADER)).toBe(false);
  });

  it("classifies methods case-insensitively", () => {
    expect(isSafeMethod("get")).toBe(true);
    expect(isSafeMethod("post")).toBe(false);
  });
});
