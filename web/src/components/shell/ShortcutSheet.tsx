import { Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";

import { t } from "../../i18n";

const ROWS: { keys: string[]; label: Parameters<typeof t>[0]; joiner?: string }[] = [
  { keys: ["?"], label: "shortcuts.open" },
  { keys: ["Ctrl", "K"], label: "shortcuts.palette", joiner: "+" },
  { keys: ["/"], label: "shortcuts.paletteSlash" },
  { keys: ["g", "q"], label: "shortcuts.goQueue" },
  { keys: ["g", "h"], label: "shortcuts.goHistory" },
  { keys: ["g", "c"], label: "shortcuts.goConfig" },
  { keys: ["Esc"], label: "shortcuts.escape" },
];

/** The `?` sheet: a modal dialog with focus trap and Esc to close (React Aria). */
export function ShortcutSheet({
  isOpen,
  onOpenChange,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <ModalOverlay
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      isDismissable
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <Modal className="w-full max-w-md rounded border border-border bg-surface p-4 text-text shadow-lg">
        <Dialog className="outline-none" aria-labelledby="shortcut-title">
          {({ close }) => (
            <>
              <Heading slot="title" id="shortcut-title" className="text-lg font-semibold">
                {t("shortcuts.title")}
              </Heading>
              <p className="mt-1 text-text-muted">{t("shortcuts.intro")}</p>
              <table className="mt-3 w-full text-left">
                <caption className="sr-only">{t("shortcuts.title")}</caption>
                <tbody>
                  {ROWS.map((row) => (
                    <tr key={row.label} className="border-t border-border">
                      <th scope="row" className="py-2 pr-3 font-normal">
                        {row.keys.map((key, index) => (
                          <span key={key}>
                            {index > 0 ? (
                              <span className="px-1 text-text-muted">
                                {row.joiner ?? t("shortcuts.sequence")}
                              </span>
                            ) : null}
                            <kbd className="rounded border border-border px-1.5 font-mono">
                              {key}
                            </kbd>
                          </span>
                        ))}
                      </th>
                      <td className="py-2">{t(row.label)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button
                type="button"
                onClick={close}
                className="mt-4 min-h-8 rounded border border-control-border bg-bg px-3 text-text"
              >
                {t("app.close")}
              </button>
            </>
          )}
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
