import { Link, useRouterState } from "@tanstack/react-router";
import {
  BookOpen,
  Clock,
  HelpCircle,
  Inbox,
  Settings,
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { BrandLogo } from "../../branding/BrandLogo";
import { useBrandName } from "../../branding/branding";
import { t } from "../../i18n";
import { LANES } from "../../lib/lanes";
import { isAdmin } from "../../lib/roles";
import { useLaneCounts } from "../../lib/useLaneCounts";
import { useMe } from "../../lib/useMe";
import { RollingCount } from "../motion/RollingCount";

const itemClass =
  "flex min-h-9 items-center gap-2.5 rounded-[var(--radius-control)] px-2.5 text-ink outline-none hover:bg-surface aria-[current=page]:bg-surface aria-[current=page]:font-medium max-[1099px]:justify-center max-[799px]:flex-1 max-[799px]:flex-col max-[799px]:gap-0.5 max-[799px]:px-1";

function Item({
  icon: Icon,
  label,
  children,
}: {
  icon: LucideIcon;
  label: string;
  children?: ReactNode;
}) {
  return (
    <>
      <Icon aria-hidden="true" size={16} strokeWidth={1.75} className="shrink-0 text-ink-2" />
      <span className="cso-rail-text min-w-0 flex-1 truncate">{label}</span>
      {children}
    </>
  );
}

/**
 * The left rail: where you are going (queue, history, config, help) and the five lanes with live
 * counts. It narrows to icons under 1100 px and becomes a bottom bar under 800 px.
 */
export function Rail({ onHelp }: { onHelp: () => void }) {
  const counts = useLaneCounts();
  const name = useBrandName();
  const { me } = useMe();
  const location = useRouterState({ select: (state) => state.location });
  const onQueue = location.pathname.startsWith("/queue");
  const activeLane = onQueue
    ? ((location.search as { lane?: string }).lane ?? undefined)
    : undefined;

  return (
    <aside className="cso-rail" aria-label={t("rail.label")}>
      <Link
        to="/queue"
        search={{}}
        className="cso-rail-brand flex items-center gap-2 px-2.5 py-1 text-base font-semibold text-ink max-[1099px]:justify-center max-[1099px]:text-center"
      >
        <BrandLogo className="h-6 w-auto shrink-0" />
        <span className="cso-rail-text" data-testid="brand-name">
          {name}
        </span>
      </Link>

      <nav aria-label={t("nav.label")} className="cso-rail-section flex flex-col gap-0.5">
        <Link
          to="/queue"
          search={{}}
          title={t("nav.queue")}
          className={itemClass}
          aria-current={onQueue && !activeLane ? "page" : undefined}
        >
          <Item icon={Inbox} label={t("nav.queue")}>
            {counts ? (
              <span className="cso-rail-text text-ink-2" data-testid="rail-total">
                <RollingCount value={counts.total} />
              </span>
            ) : null}
          </Item>
        </Link>

        <div
          role="group"
          aria-label={t("topbar.lanesLabel")}
          className="cso-rail-section my-1 flex flex-col gap-0.5 max-[1099px]:my-0"
        >
          {LANES.map((meta) => {
            const entry = counts?.entries.find((candidate) => candidate.lane === meta.lane);
            return (
              <Link
                key={meta.lane}
                to="/queue"
                search={{ lane: meta.lane }}
                title={t(meta.label)}
                data-lane={meta.lane}
                className={itemClass}
                aria-current={activeLane === meta.lane ? "page" : undefined}
              >
                <span
                  aria-hidden="true"
                  className="grid size-5 shrink-0 place-items-center rounded-[var(--radius-control)] text-xs"
                  style={{ background: meta.bg, color: meta.fg }}
                >
                  {meta.glyph}
                </span>
                <span className="cso-rail-text min-w-0 flex-1 truncate">{t(meta.label)}</span>
                {entry ? (
                  <span
                    className="cso-rail-text text-ink-2"
                    data-testid={`rail-count-${meta.lane}`}
                  >
                    <RollingCount value={entry.count} />
                  </span>
                ) : null}
              </Link>
            );
          })}
        </div>

        <Link
          to="/history"
          title={t("nav.history")}
          className={itemClass}
          activeProps={{ "aria-current": "page" }}
        >
          <Item icon={Clock} label={t("nav.history")} />
        </Link>
        <Link
          to="/config"
          title={t("nav.config")}
          className={itemClass}
          activeProps={{ "aria-current": "page" }}
        >
          <Item icon={Settings} label={t("nav.config")} />
        </Link>
        {isAdmin(me?.role) ? (
          <Link
            to="/settings"
            title={t("nav.settings")}
            className={itemClass}
            activeProps={{ "aria-current": "page" }}
            data-testid="nav-settings"
          >
            <Item icon={SlidersHorizontal} label={t("nav.settings")} />
          </Link>
        ) : null}
      </nav>

      <div className="cso-rail-section mt-auto max-[799px]:mt-0">
        <a
          href="/docs/"
          target="_blank"
          rel="noopener"
          title={t("nav.docs")}
          className={itemClass}
          data-testid="nav-docs"
        >
          <Item icon={BookOpen} label={t("nav.docs")} />
        </a>
        <button
          type="button"
          onClick={onHelp}
          aria-keyshortcuts="?"
          title={t("topbar.shortcuts")}
          className={`${itemClass} w-full text-left`}
        >
          <Item icon={HelpCircle} label={t("topbar.shortcuts")} />
        </button>
        <p
          className="cso-rail-text m-0 mt-3 px-2.5 text-xs text-ink-2 max-[1099px]:hidden"
          data-testid="rail-credit"
        >
          {t("rail.madeBy")}
        </p>
      </div>
    </aside>
  );
}
