import { client } from "../api/client.gen";
import { withCsrf } from "./csrf";

let configured = false;

/**
 * Point the generated client at this origin and wire the CSRF header.
 *
 * The OpenAPI paths already start with `/api/v1`, so the base URL is the origin itself. Cookies are
 * sent with every request (`credentials: include`); the CSRF header is added to mutating requests.
 */
export function configureApiClient(cookieSource: () => string = () => document.cookie): void {
  if (configured) return;
  configured = true;
  client.setConfig({ baseUrl: "", credentials: "include" });
  client.interceptors.request.use((request) => withCsrf(request, cookieSource()));
}
