import { useNavigate, useRouterState } from "@tanstack/react-router";
import { Command } from "cmdk";
import {
  BookOpen,
  Clock,
  Command as CommandIcon,
  Download,
  Gauge,
  HelpCircle,
  Inbox,
  LogIn,
  LogOut,
  Moon,
  Plus,
  Search,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, type ReactNode } from "react";
import { Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";

import type { Lane } from "../../api/types.gen";
import { t } from "../../i18n";
import { isTypingTarget } from "../../lib/hotkeys";
import { LANES } from "../../lib/lanes";
import { canMutate } from "../../lib/roles";
import { useMe } from "../../lib/useMe";
import { useAnnounce } from "../shell/Announcer";
import { usePrefs } from "../shell/PrefsContext";
import { useSignOut } from "../shell/useSignOut";
import { useCommandMenu } from "./CommandContext";

interface Entry {
  id: string;
  label: string;
  keywords?: string[];
  shortcut?: string;
  icon: LucideIcon | null;
  glyph?: string;
  run: () => void;
}

/** Opens the docs site in a new tab through a plain link (a fixed address, never evidence text). */
function openDocs() {
  const link = document.createElement("a");
  link.href = "/docs/";
  link.target = "_blank";
  link.rel = "noopener";
  link.click();
}

/**
 * The command menu: cmdk ranks and moves through the items, a React Aria modal supplies the focus
 * trap, Escape and focus return. Ctrl or Cmd+K toggles it everywhere (also while typing);
 * `/` opens it from any screen that does not already use `/` for its own search.
 */
export function CommandMenu({ onHelp }: { onHelp: () => void }) {
  const { isOpen, open, close, toggle, requestQueueAction } = useCommandMenu();
  const { me } = useMe();
  const navigate = useNavigate();
  const announce = useAnnounce();
  const { toggleTheme, toggleDensity } = usePrefs();
  const signOut = useSignOut();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const signedIn = me?.role === "reviewer" || me?.role === "admin";
  const mayMutate = canMutate(me?.role);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        toggle();
        return;
      }
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTypingTarget(event.target) || isOpen) return;
      if (pathname.startsWith("/queue")) return; // the queue keeps `/` for its own search box
      event.preventDefault();
      open();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggle, open, isOpen, pathname]);

  const groups = useMemo(() => {
    const goTo: Entry[] = [
      {
        id: "go-all",
        label: t("palette.allLanes"),
        shortcut: "g q",
        icon: Inbox,
        run: () => void navigate({ to: "/queue", search: {} }),
      },
      ...LANES.map<Entry>((meta) => ({
        id: `go-${meta.lane}`,
        label: t(meta.label),
        glyph: meta.glyph,
        icon: null,
        run: () => void navigate({ to: "/queue", search: { lane: meta.lane as Lane } }),
      })),
      {
        id: "go-history",
        label: t("nav.history"),
        shortcut: "g h",
        icon: Clock,
        run: () => void navigate({ to: "/history" }),
      },
      {
        id: "go-config",
        label: t("nav.config"),
        shortcut: "g c",
        icon: Settings,
        run: () => void navigate({ to: "/config" }),
      },
    ];
    const actions: Entry[] = [
      ...(mayMutate
        ? [
            {
              id: "add",
              label: t("palette.addChangeset"),
              keywords: ["new", "changeset", "id"],
              icon: Plus,
              run: () => {
                requestQueueAction("add");
                void navigate({ to: "/queue", search: {} });
              },
            } satisfies Entry,
            {
              id: "import",
              label: t("palette.import"),
              keywords: ["maproulette", "challenge"],
              icon: Download,
              run: () => {
                requestQueueAction("import");
                void navigate({ to: "/queue", search: {} });
              },
            } satisfies Entry,
          ]
        : []),
      {
        id: "theme",
        label: t("palette.toggleTheme"),
        keywords: ["dark", "light"],
        icon: Moon,
        run: toggleTheme,
      },
      {
        id: "density",
        label: t("palette.toggleDensity"),
        keywords: ["compact", "comfortable", "rows"],
        icon: Gauge,
        run: toggleDensity,
      },
      {
        id: "docs",
        label: t("nav.docs"),
        keywords: ["help", "guide", "manual"],
        icon: BookOpen,
        run: openDocs,
      },
      {
        id: "shortcuts",
        label: t("palette.shortcuts"),
        shortcut: "?",
        icon: HelpCircle,
        run: onHelp,
      },
    ];
    const account: Entry[] = [
      signedIn
        ? { id: "sign-out", label: t("nav.signOut"), icon: LogOut, run: signOut }
        : {
            id: "sign-in",
            label: t("nav.signIn"),
            icon: LogIn,
            run: () => void navigate({ to: "/login", search: { redirect: undefined } }),
          },
    ];
    return [
      { key: "goTo", heading: t("palette.group.goTo"), entries: goTo },
      { key: "actions", heading: t("palette.group.actions"), entries: actions },
      { key: "account", heading: t("palette.group.account"), entries: account },
    ];
  }, [
    mayMutate,
    signedIn,
    navigate,
    requestQueueAction,
    toggleTheme,
    toggleDensity,
    onHelp,
    signOut,
  ]);

  function choose(entry: Entry) {
    close();
    announce(t("palette.announce", { label: entry.label }));
    // Let the modal release focus first so a dialog the action opens can take it.
    window.setTimeout(entry.run, 0);
  }

  return (
    <ModalOverlay
      isOpen={isOpen}
      onOpenChange={(next) => (next ? open() : close())}
      isDismissable
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/40 p-3 pt-[12dvh]"
    >
      <Modal className="cso-pop w-full max-w-[560px] overflow-hidden rounded-[var(--radius-pane)] border border-line bg-surface text-ink">
        <Dialog className="outline-none" aria-label={t("palette.title")}>
          <Heading slot="title" className="sr-only">
            {t("palette.title")}
          </Heading>
          {/* cmdk names its input from this label, so it carries the input's name. */}
          <Command loop label={t("palette.inputLabel")} className="flex w-full flex-col">
            <div className="flex items-center gap-2 border-b border-line px-3">
              <Search aria-hidden="true" size={16} strokeWidth={1.75} className="text-ink-2" />
              <Command.Input
                ref={(element) => element?.focus()}
                placeholder={t("palette.placeholder")}
                className="h-11 w-full bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-2"
              />
            </div>
            <Command.List className="max-h-[min(360px,60dvh)] overflow-y-auto overscroll-contain p-1.5">
              <Command.Empty className="px-3 py-6 text-center text-ink-2">
                {t("palette.empty")}
              </Command.Empty>
              {groups.map((group) => (
                <Command.Group
                  key={group.key}
                  heading={group.heading}
                  className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-ink-2"
                >
                  {group.entries.map((entry) => (
                    <Item key={entry.id} entry={entry} onChoose={choose} />
                  ))}
                </Command.Group>
              ))}
            </Command.List>
            <div className="flex items-center gap-3 border-t border-line px-3 py-2 text-xs text-ink-2">
              <CommandIcon aria-hidden="true" size={14} strokeWidth={1.75} />
              <span>{t("palette.footer")}</span>
            </div>
          </Command>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}

function Item({ entry, onChoose }: { entry: Entry; onChoose: (entry: Entry) => void }): ReactNode {
  const Icon = entry.icon;
  return (
    <Command.Item
      value={entry.label}
      keywords={entry.keywords}
      onSelect={() => onChoose(entry)}
      data-testid={`palette-${entry.id}`}
      className="flex cursor-pointer select-none items-center gap-2.5 rounded-[var(--radius-control)] px-2.5 py-2 text-[13px] outline-none data-[selected=true]:bg-surface-2"
    >
      {Icon ? (
        <Icon aria-hidden="true" size={16} strokeWidth={1.75} className="text-ink-2" />
      ) : (
        <span aria-hidden="true" className="w-4 text-center text-ink-2">
          {entry.glyph}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate">{entry.label}</span>
      {entry.shortcut ? (
        <span className="flex gap-1" aria-hidden="true">
          {entry.shortcut.split(" ").map((key) => (
            <kbd
              key={key}
              className="grid h-5 min-w-5 place-items-center rounded-[5px] bg-surface-2 px-1 font-sans text-[11px] text-ink-2"
            >
              {key}
            </kbd>
          ))}
        </span>
      ) : null}
    </Command.Item>
  );
}
