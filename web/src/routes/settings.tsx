import { createRoute, lazyRouteComponent } from "@tanstack/react-router";

import { appRoute } from "./layouts";

/** `/settings`: admin only. Workspace wording, the review pack in force, invite codes, export. */
export const settingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/settings",
  component: lazyRouteComponent(() => import("./settings.page"), "SettingsPage"),
});
