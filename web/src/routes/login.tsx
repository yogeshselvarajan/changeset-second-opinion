import { createRoute, lazyRouteComponent } from "@tanstack/react-router";

import { appRoute } from "./layouts";

/** `/login?redirect=/path`: invite code and display name; returns to the intended page. */
export const loginRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/login",
  validateSearch: (search: Record<string, unknown>): { redirect?: string; osm_error?: string } => ({
    redirect: typeof search.redirect === "string" ? search.redirect : undefined,
    osm_error: typeof search.osm_error === "string" ? search.osm_error : undefined,
  }),
  component: lazyRouteComponent(() => import("./login.page"), "LoginPage"),
});
