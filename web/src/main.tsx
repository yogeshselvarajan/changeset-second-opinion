import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";
import { configureApiClient } from "./lib/api";
import { applyPrefs, readPrefs } from "./lib/prefs";
import { router } from "./router";

// Apply the saved theme and density before the first paint, then wire the API client.
applyPrefs(readPrefs());
configureApiClient();

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

const container = document.getElementById("root");
if (!container) throw new Error("Missing #root element");

// Route components load on demand. Waiting for the matched route's code before the first render
// keeps the prerendered page on screen until its live version is ready, so it never flashes empty.
await router.load();

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
