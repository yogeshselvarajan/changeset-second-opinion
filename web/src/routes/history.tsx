import { createRoute, lazyRouteComponent } from "@tanstack/react-router";

import { appRoute } from "./layouts";

export interface HistorySearch {
  reviewer?: string;
  disposition?: string;
  from?: string;
  to?: string;
}

const text = (value: unknown): string | undefined =>
  typeof value === "string" && value !== "" ? value : undefined;

/** `/history?reviewer&disposition&from&to` */
export const historyRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/history",
  validateSearch: (search: Record<string, unknown>): HistorySearch => ({
    reviewer: text(search.reviewer),
    disposition: text(search.disposition),
    from: text(search.from),
    to: text(search.to),
  }),
  component: lazyRouteComponent(() => import("./history.page"), "HistoryPage"),
});
