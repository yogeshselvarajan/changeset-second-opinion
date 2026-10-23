import { createRouter } from "@tanstack/react-router";

import { RouteError } from "./components/shell/RouteError";
import { rootRoute } from "./routes/__root";
import { caseRoute } from "./routes/cases.$id";
import { draftRoute } from "./routes/cases";
import { configRoute } from "./routes/config";
import { historyRoute } from "./routes/history";
import { aboutRoute, indexRoute, privacyRoute } from "./routes/index";
import { appRoute, publicRoute } from "./routes/layouts";
import { loginRoute } from "./routes/login";
import { queueRoute } from "./routes/queue";
import { receiptRoute } from "./routes/r.$runId";
import { settingsRoute } from "./routes/settings";

const routeTree = rootRoute.addChildren([
  appRoute.addChildren([
    queueRoute,
    caseRoute,
    draftRoute,
    historyRoute,
    configRoute,
    settingsRoute,
    loginRoute,
  ]),
  publicRoute.addChildren([indexRoute, aboutRoute, privacyRoute, receiptRoute]),
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  defaultErrorComponent: RouteError,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
