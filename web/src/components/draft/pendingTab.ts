/**
 * A tab opened inside the click handler, before any `await`. Browsers only let `window.open` through
 * a popup blocker while the click's user activation is fresh, and recording an outcome and copying
 * take several awaits. The tab starts blank and is sent to the changeset page once the outcome is
 * recorded, or closed if it was not. `opener` is cleared, which is what `noopener` would do (it
 * cannot be passed here because that makes `window.open` return null).
 */
export interface PendingTab {
  go(url: string): void;
  close(): void;
}

export function openPendingTab(): PendingTab {
  let tab: Window | null = null;
  try {
    tab = window.open("", "_blank");
    if (tab) tab.opener = null;
  } catch {
    tab = null;
  }
  return {
    go(url) {
      if (tab && !tab.closed) tab.location.href = url;
    },
    close() {
      if (tab && !tab.closed) tab.close();
    },
  };
}
