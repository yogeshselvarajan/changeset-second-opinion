import { AppShell } from "../components/shell/AppShell";
import { NotFoundPage } from "../components/shell/ErrorPages";

export function NotFoundRoute() {
  return (
    <AppShell>
      <NotFoundPage />
    </AppShell>
  );
}
