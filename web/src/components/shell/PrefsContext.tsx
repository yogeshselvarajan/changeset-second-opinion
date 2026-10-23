import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { t } from "../../i18n";
import {
  applyPrefs,
  readPrefs,
  writePrefs,
  type Density,
  type Prefs,
  type Theme,
} from "../../lib/prefs";
import { useAnnounce } from "./Announcer";

interface PrefsApi {
  prefs: Prefs;
  setTheme: (theme: Theme) => void;
  setDensity: (density: Density) => void;
  /** Light and dark swap; "system" resolves through the current system setting first. */
  toggleTheme: () => void;
  toggleDensity: () => void;
}

const PrefsContext = createContext<PrefsApi | null>(null);

function systemIsDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

/** The one owner of theme and density: the selects and the command menu both go through it. */
export function PrefsProvider({ children }: { children: ReactNode }) {
  const announce = useAnnounce();
  const [prefs, setPrefs] = useState<Prefs>(() => readPrefs());

  useEffect(() => {
    applyPrefs(prefs);
  }, [prefs]);

  const update = useCallback(
    (next: Prefs, message: string) => {
      setPrefs(next);
      writePrefs(next);
      announce(message);
    },
    [announce],
  );

  const setTheme = useCallback(
    (theme: Theme) =>
      update({ ...prefs, theme }, t("prefs.announceTheme", { value: t(`prefs.theme.${theme}`) })),
    [prefs, update],
  );
  const setDensity = useCallback(
    (density: Density) =>
      update(
        { ...prefs, density },
        t("prefs.announceDensity", { value: t(`prefs.density.${density}`) }),
      ),
    [prefs, update],
  );

  const value = useMemo<PrefsApi>(
    () => ({
      prefs,
      setTheme,
      setDensity,
      toggleTheme: () => {
        const dark = prefs.theme === "dark" || (prefs.theme === "system" && systemIsDark());
        setTheme(dark ? "light" : "dark");
      },
      toggleDensity: () => setDensity(prefs.density === "compact" ? "comfortable" : "compact"),
    }),
    [prefs, setTheme, setDensity],
  );

  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs(): PrefsApi {
  const value = useContext(PrefsContext);
  if (!value) throw new Error("usePrefs needs a PrefsProvider");
  return value;
}
