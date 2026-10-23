import { Link, useRouterState } from "@tanstack/react-router";
import { Search } from "lucide-react";

import { useBrandName } from "../../branding/branding";
import { t } from "../../i18n";
import { useMe } from "../../lib/useMe";
import { useCommandMenu } from "../command/CommandContext";
import { ModeBadge } from "./ModeBanner";
import { PrefsControls } from "./PrefsControls";
import { RoleBadge } from "./RoleBadge";
import { useSignOut } from "./useSignOut";

const buttonClass = "cso-ghostbtn";

/** Where the person is, as a short breadcrumb taken from the address. */
function crumb(pathname: string): string {
  if (pathname.startsWith("/cases/")) {
    const parts = pathname.split("/").filter(Boolean);
    const id = parts[1] ?? "";
    return parts[2] === "draft" ? t("topstrip.draft", { id }) : t("topstrip.case", { id });
  }
  if (pathname.startsWith("/history")) return t("nav.history");
  if (pathname.startsWith("/config")) return t("nav.config");
  if (pathname.startsWith("/settings")) return t("nav.settings");
  if (pathname.startsWith("/login")) return t("nav.signIn");
  return t("nav.queue");
}

/** The quiet strip over the content: breadcrumb, a search field that opens the menu, identity. */
export function TopStrip() {
  const { me } = useMe();
  const name = useBrandName();
  const { open } = useCommandMenu();
  const signOut = useSignOut();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const signedIn = me?.role === "reviewer" || me?.role === "admin";

  return (
    <header
      aria-label={t("topbar.label")}
      className="cso-top border-b border-line bg-surface px-4 py-2"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Link
          to="/queue"
          search={{}}
          className="hidden text-base font-semibold text-ink max-[799px]:inline-flex"
        >
          {name}
        </Link>
        <p className="m-0 text-base font-medium text-ink" data-testid="breadcrumb">
          {crumb(pathname)}
        </p>

        <button
          type="button"
          onClick={open}
          aria-keyshortcuts="Control+K Meta+K"
          title={t("topstrip.search")}
          data-testid="palette-trigger"
          className="cso-search ml-auto flex min-h-9 min-w-[10rem] flex-1 items-center gap-2 px-3 text-left text-ink-2 sm:max-w-sm sm:flex-none"
        >
          <Search aria-hidden="true" size={14} strokeWidth={1.75} />
          <span className="flex-1 truncate">{t("topstrip.searchPlaceholder")}</span>
          <kbd
            aria-hidden="true"
            className="rounded-[5px] bg-surface-2 px-1 font-sans text-[11px] text-ink-2 max-[799px]:hidden"
          >
            Ctrl K
          </kbd>
        </button>

        <div className="flex flex-wrap items-center gap-2">
          <ModeBadge mode={me?.mode} />
          <RoleBadge userRole={me?.role} name={me?.display_name} viaOsm={me?.via_osm ?? false} />
          <PrefsControls />
          {signedIn ? (
            <button type="button" onClick={signOut} className={buttonClass}>
              {t("nav.signOut")}
            </button>
          ) : (
            <Link to="/login" search={{ redirect: undefined }} className={buttonClass}>
              {t("nav.signIn")}
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
