import { useRouterState } from "@tanstack/react-router";

import { Seo } from "./Seo";
import { routeTitle } from "./routeTitle";

/** Title for the current app screen, and `noindex`: nothing behind the sign-in is for search. */
export function AppSeo() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  return <Seo title={routeTitle(pathname)} noindex />;
}
