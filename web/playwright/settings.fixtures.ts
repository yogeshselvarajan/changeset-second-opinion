import type { Page, Route } from "@playwright/test";

export interface InviteFixture {
  id: string;
  label: string;
  role: "reviewer" | "admin";
  created_at: string;
  created_by: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  max_uses: number | null;
  use_count: number;
  status: "active" | "expired" | "revoked" | "spent";
}

export interface SettingsMockState {
  version: number;
  name: string;
  tagline: string;
  accent_hex: string;
  accent_dark_hex: string;
  community_paragraph: string;
  logo_svg: string | null;
  osm_signin_enabled: boolean;
  osm_signin_configured: boolean;
  invites: InviteFixture[];
  /** Every PUT /settings, as the server saw it. */
  puts: { body: Record<string, unknown>; ifMatch: string | undefined; csrf: string | undefined }[];
  /** Created and revoked invites, as the server saw them. */
  created: Record<string, unknown>[];
  revoked: string[];
  /** The next PUT meets a newer version (someone else saved first). */
  conflictNext: boolean;
  /** The next PUT is refused with these field messages. */
  rejectNext: Record<string, string> | null;
  /** A PUT that fails with a server error. */
  failNext: boolean;
}

export function newSettingsState(overrides: Partial<SettingsMockState> = {}): SettingsMockState {
  return {
    version: 1,
    name: "Changeset Second Opinion",
    tagline: "A second opinion on flagged OpenStreetMap edits. Evidence first; a person posts.",
    accent_hex: "#4E5BD8",
    accent_dark_hex: "#6772DD",
    community_paragraph: "A community can pick a pack of settings.",
    logo_svg: null,
    osm_signin_enabled: true,
    osm_signin_configured: true,
    invites: [
      {
        id: "00000000-0000-4000-8000-000000000a01",
        label: "Lyon team",
        role: "reviewer",
        created_at: "2026-10-01T09:00:00Z",
        created_by: "admin:Test Admin",
        expires_at: null,
        revoked_at: null,
        max_uses: 5,
        use_count: 2,
        status: "active",
      },
      {
        id: "00000000-0000-4000-8000-000000000a02",
        label: "Old trial",
        role: "reviewer",
        created_at: "2026-09-01T09:00:00Z",
        created_by: null,
        expires_at: null,
        revoked_at: "2026-09-10T09:00:00Z",
        max_uses: null,
        use_count: 0,
        status: "revoked",
      },
    ],
    puts: [],
    created: [],
    revoked: [],
    conflictNext: false,
    rejectNext: null,
    failNext: false,
    ...overrides,
  };
}

const problem = (status: number, title: string, extra: Record<string, unknown> = {}) => ({
  type: `urn:cso:problem:${status}`,
  title,
  status,
  request_id: "req-test",
  ...extra,
});

function reply(route: Route, status: number, body: unknown, headers: Record<string, string> = {}) {
  return route.fulfill({
    status,
    contentType: status >= 400 ? "application/problem+json" : "application/json",
    headers,
    body: JSON.stringify(body),
  });
}

/** Same arithmetic as the server: the larger over the smaller luminance, each plus 0.05. */
function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}
function ratio(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

export function settingsBody(state: SettingsMockState) {
  return {
    name: state.name,
    tagline: state.tagline,
    accent_hex: state.accent_hex,
    accent_dark_hex: state.accent_dark_hex,
    accent_contrast_light: ratio(state.accent_hex, "#F6F5F2"),
    accent_contrast_dark: ratio(state.accent_dark_hex, "#0F1012"),
    community_paragraph: state.community_paragraph,
    logo_svg: state.logo_svg,
    osm_signin_enabled: state.osm_signin_enabled,
    osm_signin_configured: state.osm_signin_configured,
    active_pack: "default",
    calibration_version: null,
    updated_at: "2026-10-19T10:00:00Z",
    version: state.version,
  };
}

export function brandingBody(state: SettingsMockState) {
  return {
    name: state.name,
    tagline: state.tagline,
    accent_hex: state.accent_hex,
    accent_dark_hex: state.accent_dark_hex,
    community_paragraph: state.community_paragraph,
    has_logo: state.logo_svg !== null,
    osm_signin_enabled: state.osm_signin_enabled && state.osm_signin_configured,
  };
}

/** Register after `mockApi`: later routes win. Answers settings, branding and invites. */
export async function mockSettingsApi(page: Page, state: SettingsMockState): Promise<void> {
  await page.route("**/api/v1/public/branding", (route) =>
    reply(route, 200, brandingBody(state), { "cache-control": "public, max-age=300" }),
  );

  await page.route("**/api/v1/settings", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      return reply(route, 200, settingsBody(state), { etag: `W/"${state.version}"` });
    }
    const body = request.postDataJSON() as Record<string, unknown>;
    const headers = request.headers();
    state.puts.push({ body, ifMatch: headers["if-match"], csrf: headers["x-csrf"] });
    if (state.failNext) {
      state.failNext = false;
      return reply(route, 500, problem(500, "Server error"));
    }
    if (state.conflictNext || headers["if-match"] !== `W/"${state.version}"`) {
      state.conflictNext = false;
      state.version += 1; // the other save
      return reply(
        route,
        412,
        problem(412, "Precondition failed", { current: { version: state.version } }),
      );
    }
    if (state.rejectNext) {
      const errors = Object.entries(state.rejectNext).map(([field, msg]) => ({
        loc: ["body", field],
        msg,
        type: "value_error",
      }));
      state.rejectNext = null;
      return reply(route, 422, problem(422, "Unprocessable", { errors }));
    }
    Object.assign(state, {
      name: body.name,
      tagline: body.tagline,
      accent_hex: body.accent_hex,
      community_paragraph: body.community_paragraph,
      logo_svg: body.logo_svg ?? null,
      osm_signin_enabled: body.osm_signin_enabled,
    });
    state.version += 1;
    return reply(route, 200, settingsBody(state), { etag: `W/"${state.version}"` });
  });

  await page.route("**/api/v1/invites", async (route) => {
    const request = route.request();
    if (request.method() === "GET") return reply(route, 200, { items: state.invites });
    const body = request.postDataJSON() as Record<string, unknown>;
    state.created.push(body);
    const invite: InviteFixture = {
      id: `00000000-0000-4000-8000-00000000b0${state.created.length}`,
      label: String(body.label ?? ""),
      role: (body.role as "reviewer" | "admin") ?? "reviewer",
      created_at: "2026-10-19T10:00:00Z",
      created_by: "admin:Test Admin",
      expires_at: null,
      revoked_at: null,
      max_uses: (body.max_uses as number | null) ?? null,
      use_count: 0,
      status: "active",
    };
    state.invites.unshift(invite);
    return reply(route, 201, { code: "cso-test-code-shown-once", invite });
  });

  await page.route("**/api/v1/invites/*/revoke", async (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-2) ?? "";
    const invite = state.invites.find((item) => item.id === id);
    if (!invite) return reply(route, 404, problem(404, "Not found"));
    state.revoked.push(id);
    invite.status = "revoked";
    invite.revoked_at = "2026-10-19T10:05:00Z";
    return reply(route, 200, invite);
  });
}
