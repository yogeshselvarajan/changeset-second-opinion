import { createRoute, lazyRouteComponent } from "@tanstack/react-router";

import { parseSearch, type QueueSearch } from "../components/queue/search";
import { appRoute } from "./layouts";

export type { QueueSearch };

/** `/queue?lane&status&editor&q&stale&cursor`: filters live in the URL so a view can be shared. */
export const queueRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/queue",
  validateSearch: (search: Record<string, unknown>): QueueSearch => parseSearch(search),
  component: lazyRouteComponent(() => import("./queue.page"), "QueueRoute"),
});
