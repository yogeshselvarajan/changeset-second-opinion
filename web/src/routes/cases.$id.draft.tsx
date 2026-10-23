import { createRoute, lazyRouteComponent } from "@tanstack/react-router";

import { appRoute } from "./layouts";

/** `/cases/$id/draft`: the draft editor. `$id` is the case uuid, not the changeset id. */
export const draftRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/cases/$id/draft",
  component: lazyRouteComponent(() => import("./cases.$id.draft.page"), "DraftPage"),
});
