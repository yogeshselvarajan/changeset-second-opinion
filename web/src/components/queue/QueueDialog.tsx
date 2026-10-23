import type { ReactNode } from "react";
import { Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";

/** A modal dialog with a title: focus is trapped, Esc and the backdrop close it (React Aria). */
export function QueueDialog({
  isOpen,
  onOpenChange,
  title,
  children,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
}) {
  return (
    <ModalOverlay
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      isDismissable
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[3px]"
    >
      <Modal className="cso-pop w-full max-w-md rounded-[var(--radius-pane)] border border-line bg-surface p-6 text-text shadow-2xl">
        <Dialog className="outline-none">
          <Heading slot="title" className="m-0 font-display text-xl font-semibold">
            {title}
          </Heading>
          {children}
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}

export const controlClass =
  "min-h-9 cursor-pointer rounded-[var(--radius-control)] border border-control-border bg-surface px-3.5 text-text hover:bg-surface-2 disabled:cursor-default disabled:opacity-60";
export const fieldClass =
  "mt-1 block min-h-9 w-full rounded-[var(--radius-control)] border border-control-border bg-surface px-3 text-text";
