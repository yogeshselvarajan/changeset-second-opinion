import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from "react";

/** What the queue can be asked to open from anywhere (the palette and the "+" menu use this). */
export type QueueAction = "add" | "import";

interface CommandApi {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
  /** Element that had focus before the palette opened, so Escape can return to it. */
  returnFocusTo: MutableRefObject<HTMLElement | null>;
  /** A request for the queue to open its add or import dialog; the queue clears it once handled. */
  queueAction: QueueAction | null;
  requestQueueAction: (action: QueueAction) => void;
  clearQueueAction: () => void;
}

const CommandContext = createContext<CommandApi | null>(null);

function activeElement(): HTMLElement | null {
  return document.activeElement instanceof HTMLElement ? document.activeElement : null;
}

export function CommandProvider({ children }: { children: ReactNode }) {
  const [isOpen, setOpen] = useState(false);
  const [queueAction, setQueueAction] = useState<QueueAction | null>(null);
  const returnFocusTo = useRef<HTMLElement | null>(null);

  const open = useCallback(() => {
    returnFocusTo.current = activeElement();
    setOpen(true);
  }, []);
  const close = useCallback(() => setOpen(false), []);
  const toggle = useCallback(() => {
    setOpen((current) => {
      if (!current) returnFocusTo.current = activeElement();
      return !current;
    });
  }, []);
  const requestQueueAction = useCallback((action: QueueAction) => setQueueAction(action), []);
  const clearQueueAction = useCallback(() => setQueueAction(null), []);

  const value = useMemo<CommandApi>(
    () => ({
      isOpen,
      open,
      close,
      toggle,
      returnFocusTo,
      queueAction,
      requestQueueAction,
      clearQueueAction,
    }),
    [isOpen, open, close, toggle, queueAction, requestQueueAction, clearQueueAction],
  );
  return <CommandContext.Provider value={value}>{children}</CommandContext.Provider>;
}

export function useCommandMenu(): CommandApi {
  const value = useContext(CommandContext);
  if (!value) throw new Error("useCommandMenu needs a CommandProvider");
  return value;
}
