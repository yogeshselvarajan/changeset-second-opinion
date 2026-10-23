import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { t } from "../../i18n";

type Announce = (message: string) => void;

const AnnounceContext = createContext<Announce>(() => {});

/** Polite live region for short status messages ("Signed in", "Theme set to Dark"). */
export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState("");
  const [tick, setTick] = useState(0);
  const announce = useCallback((next: string) => {
    setMessage(next);
    setTick((value) => value + 1); // lets the same message be announced twice
  }, []);
  const value = useMemo(() => announce, [announce]);
  return (
    <AnnounceContext.Provider value={value}>
      {children}
      <div role="status" aria-live="polite" aria-label={t("app.liveRegion")} className="sr-only">
        <span key={tick}>{message}</span>
      </div>
    </AnnounceContext.Provider>
  );
}

export function useAnnounce(): Announce {
  return useContext(AnnounceContext);
}
