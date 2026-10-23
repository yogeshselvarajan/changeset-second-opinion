import { Outlet } from "@tanstack/react-router";
import { useCallback, useState, type ReactNode } from "react";

import { AppSeo } from "../../seo/AppSeo";
import { CommandProvider } from "../command/CommandContext";
import { CommandMenu } from "../command/CommandMenu";
import { AnnouncerProvider } from "./Announcer";
import { AppFrame } from "./AppFrame";
import { ErrorBoundary } from "./ErrorPages";
import { GlobalShortcuts } from "./GlobalShortcuts";
import { PrefsProvider } from "./PrefsContext";
import { ShortcutSheet } from "./ShortcutSheet";

/**
 * The frame around every app route: rail, top strip, main landmark, command menu, live region.
 * It shows the matched route, or `children` when given (the not-found page).
 */
export function AppShell({ children }: { children?: ReactNode }) {
  const [helpOpen, setHelpOpen] = useState(false);
  const openHelp = useCallback(() => setHelpOpen(true), []);

  return (
    <AnnouncerProvider>
      <PrefsProvider>
        <AppSeo />
        <CommandProvider>
          <AppFrame onHelp={openHelp}>
            <ErrorBoundary>{children ?? <Outlet />}</ErrorBoundary>
          </AppFrame>
          <CommandMenu onHelp={openHelp} />
          <GlobalShortcuts onHelp={openHelp} />
          <ShortcutSheet isOpen={helpOpen} onOpenChange={setHelpOpen} />
        </CommandProvider>
      </PrefsProvider>
    </AnnouncerProvider>
  );
}
