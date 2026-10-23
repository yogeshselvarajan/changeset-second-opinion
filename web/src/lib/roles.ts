import type { Role } from "../api/types.gen";

/** Viewers browse; reviewers and admins may change things (the server enforces it too). */
export function canMutate(role: Role | undefined): boolean {
  return role === "reviewer" || role === "admin";
}

export function isAdmin(role: Role | undefined): boolean {
  return role === "admin";
}

/**
 * A safe in-app return path for after login: a single leading slash and nothing that can leave the
 * site (no scheme, no `//host`, no backslash tricks). Anything else becomes the queue.
 */
export function safeRedirect(value: unknown): string {
  if (typeof value !== "string") return "/queue";
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return "/queue";
  if ([...value].some((char) => char.charCodeAt(0) < 0x20)) return "/queue";
  return value;
}
