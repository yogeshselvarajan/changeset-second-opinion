import { createRoute, lazyRouteComponent } from "@tanstack/react-router";

import { publicRoute } from "./layouts";

/**
 * `/`: the home page. It is prerendered to static HTML at build time and works without the API; when
 * the API answers, the workspace's own name, logo, accent and paragraph replace the built-in ones.
 */
export const indexRoute = createRoute({
  getParentRoute: () => publicRoute,
  path: "/",
  component: lazyRouteComponent(() => import("../landing/LandingRoutes"), "HomePage"),
});

/** `/about` */
export const aboutRoute = createRoute({
  getParentRoute: () => publicRoute,
  path: "/about",
  component: lazyRouteComponent(() => import("../landing/LandingRoutes"), "AboutPage"),
});

/** `/privacy` */
export const privacyRoute = createRoute({
  getParentRoute: () => publicRoute,
  path: "/privacy",
  component: lazyRouteComponent(() => import("../landing/LandingRoutes"), "PrivacyPage"),
});
