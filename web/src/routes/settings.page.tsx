import { ForbiddenPage } from "../components/shell/ErrorPages";
import { SettingsScreen } from "../components/settings/SettingsScreen";
import { t } from "../i18n";
import { isAdmin } from "../lib/roles";
import { useMe } from "../lib/useMe";

export function SettingsPage() {
  const { me, isPending } = useMe();
  if (isPending) return <p className="p-4 text-text-muted">{t("app.loading")}</p>;
  // The server enforces this too; the page just shows the 403 view instead of a broken screen.
  if (!isAdmin(me?.role)) return <ForbiddenPage />;
  return <SettingsScreen />;
}
