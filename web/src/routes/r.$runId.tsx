import { createRoute, lazyRouteComponent } from "@tanstack/react-router";

import { publicRoute } from "./layouts";

/** `/r/$runId`: a decision receipt anyone with the link can read; no account, no shell. */
export const receiptRoute = createRoute({
  getParentRoute: () => publicRoute,
  path: "/r/$runId",
  component: lazyRouteComponent(() => import("./r.$runId.page"), "ReceiptPage"),
});
