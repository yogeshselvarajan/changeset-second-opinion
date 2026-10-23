import { createRoute, lazyRouteComponent } from "@tanstack/react-router";

import { appRoute } from "./layouts";

/** `/cases/$id`: the case screen. `$id` is the case id (a uuid), as the queue lists it. */
export const caseRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/cases/$id",
  component: lazyRouteComponent(() => import("./cases.$id.page"), "CasePage"),
});
