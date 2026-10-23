import { describe, expect, it } from "vitest";

import { canMutate, isAdmin, safeRedirect } from "./roles";

describe("roles", () => {
  it("lets only reviewers and admins change things", () => {
    expect(canMutate("viewer")).toBe(false);
    expect(canMutate(undefined)).toBe(false);
    expect(canMutate("reviewer")).toBe(true);
    expect(canMutate("admin")).toBe(true);
  });

  it("limits config to admins", () => {
    expect(isAdmin("admin")).toBe(true);
    expect(isAdmin("reviewer")).toBe(false);
  });
});

describe("safeRedirect", () => {
  it("keeps in-app paths with their query", () => {
    expect(safeRedirect("/cases/abc?x=1")).toBe("/cases/abc?x=1");
  });

  it.each([
    "https://evil.example/",
    "//evil.example",
    "/\\evil.example",
    "javascript:alert(1)",
    "cases",
    "/a\nb",
    "",
    42,
    undefined,
    null,
  ])("sends %s to the queue", (value) => {
    expect(safeRedirect(value)).toBe("/queue");
  });
});
