import { describe, expect, it } from "vitest";

import { t } from "./i18n";

describe("t", () => {
  it("returns the message", () => {
    expect(t("app.name")).toBe("Changeset Second Opinion");
  });

  it("fills placeholders", () => {
    expect(t("login.error.rateLimited", { seconds: 30 })).toContain("30 seconds");
  });

  it("leaves an unknown placeholder visible instead of printing undefined", () => {
    expect(t("login.error.rateLimited", {})).toContain("{seconds}");
  });
});
