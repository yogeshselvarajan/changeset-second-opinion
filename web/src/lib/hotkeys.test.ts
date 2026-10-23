import { describe, expect, it } from "vitest";

import { createSequenceMatcher, isTypingTarget } from "./hotkeys";

const bindings = { "?": "help", "g h": "history", "g c": "config", "g q": "queue" };

describe("createSequenceMatcher", () => {
  it("fires single keys immediately", () => {
    expect(createSequenceMatcher(bindings).press("?", 0)).toBe("help");
  });

  it("completes a two-key sequence", () => {
    const matcher = createSequenceMatcher(bindings);
    expect(matcher.press("g", 0)).toBeNull();
    expect(matcher.press("h", 100)).toBe("history");
  });

  it("forgets a pending prefix after the timeout", () => {
    const matcher = createSequenceMatcher(bindings, 1000);
    matcher.press("g", 0);
    expect(matcher.press("h", 1500)).toBeNull();
  });

  it("drops a pending prefix when the next key does not complete it", () => {
    const matcher = createSequenceMatcher(bindings);
    matcher.press("g", 0);
    expect(matcher.press("x", 10)).toBeNull();
    expect(matcher.press("h", 20)).toBeNull();
  });

  it("lets a new prefix start right after a failed sequence", () => {
    const matcher = createSequenceMatcher(bindings);
    matcher.press("g", 0);
    matcher.press("g", 10);
    expect(matcher.press("c", 20)).toBe("config");
  });

  it("returns null for unbound keys", () => {
    expect(createSequenceMatcher(bindings).press("z", 0)).toBeNull();
  });
});

describe("isTypingTarget", () => {
  it("is true for inputs, textareas, selects and editable content", () => {
    expect(isTypingTarget(document.createElement("input"))).toBe(true);
    expect(isTypingTarget(document.createElement("textarea"))).toBe(true);
    expect(isTypingTarget(document.createElement("select"))).toBe(true);
    const editable = document.createElement("div");
    Object.defineProperty(editable, "isContentEditable", { value: true });
    expect(isTypingTarget(editable)).toBe(true);
  });

  it("is false for buttons, the body and non-elements", () => {
    expect(isTypingTarget(document.createElement("button"))).toBe(false);
    expect(isTypingTarget(document.body)).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});
