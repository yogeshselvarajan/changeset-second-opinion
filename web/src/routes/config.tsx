import { createRoute, lazyRouteComponent } from "@tanstack/react-router";

import { appRoute } from "./layouts";

/** `/config`: admin only. */
export const configRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/config",
  component: lazyRouteComponent(() => import("./config.page"), "ConfigPage"),
});
