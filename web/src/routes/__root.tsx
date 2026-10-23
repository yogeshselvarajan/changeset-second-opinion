import { Outlet, createRootRoute, lazyRouteComponent } from "@tanstack/react-router";

/**
 * The root only hands over to a layout group (see `layouts.tsx`). An unknown address gets the app
 * shell with a not-found page; that shell loads on demand, so the public pages do not carry it.
 */
export const rootRoute = createRootRoute({
  component: Outlet,
  notFoundComponent: lazyRouteComponent(() => import("./not-found.page"), "NotFoundRoute"),
});
