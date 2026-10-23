import { Outlet, createRoute, lazyRouteComponent } from "@tanstack/react-router";

import { PublicLayout } from "../landing/PublicLayout";
import { rootRoute } from "./__root";

/**
 * Two groups of routes. The app group (sign-in, queue, case, history, config) sits inside the
 * shell with its sidebar and sign-in state, and loads on demand so the public pages never carry it.
 * The public group (the home page, about, privacy and receipts) has its own light frame, needs no
 * account and makes no calls the page does not need.
 */
export const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  component: lazyRouteComponent(() => import("../components/shell/AppShell"), "AppShell"),
});

export const publicRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "public",
  component: () => (
    <PublicLayout>
      <Outlet />
    </PublicLayout>
  ),
});
