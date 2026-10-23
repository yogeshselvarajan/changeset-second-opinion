import { Heart } from "lucide-react";
import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";

import { BrandLogo } from "../branding/BrandLogo";
import { useBranding } from "../branding/branding";
import { t } from "../i18n";
import {
  LESS_MOTION_EVENT,
  readLessMotion,
  restoreLessMotion,
  setLessMotion,
} from "../motion/less";
import { copy, REPO_URL } from "./copy";
import "./landing.css";

const LINKS = [
  { href: "/#how", label: copy.nav.how },
  { href: "/#receipt", label: copy.nav.receipts },
  { href: "/#communities", label: copy.nav.communities },
  { href: "/#open-source", label: copy.nav.openSource },
  { href: "/about", label: copy.nav.about },
  { href: "/docs/", label: copy.nav.docs },
] as const;

/** "Less motion": the same as the system setting, for this site only, remembered in the browser. */
function MotionSwitch() {
  // The server render and the first browser render both say "off"; the stored choice follows.
  const less = useSyncExternalStore(
    (onChange) => {
      window.addEventListener(LESS_MOTION_EVENT, onChange);
      return () => window.removeEventListener(LESS_MOTION_EVENT, onChange);
    },
    readLessMotion,
    () => false,
  );
  return (
    <button
      type="button"
      className="motion-switch"
      aria-pressed={less}
      aria-label={copy.footer.motionLabel}
      data-testid="motion-switch"
      onClick={() => setLessMotion(!less)}
    >
      {less ? copy.footer.fullMotion : copy.footer.lessMotion}
    </button>
  );
}

const footerLink =
  "inline-flex min-h-8 items-center text-ink-2 underline-offset-4 hover:text-ink hover:underline";

/**
 * The frame for every public page: a floating top bar, the page, and a footer. It uses plain
 * anchors and no router, so the same markup is rendered to static HTML at build time and again in
 * the browser. The app is a separate bundle that a plain link reaches with a normal page load.
 */
export function PublicLayout({
  children,
  name: fallbackName = copy.name,
}: {
  children: ReactNode;
  name?: string;
}) {
  // The workspace's own name and logo replace the built-in ones once the server has answered.
  const name = useBranding()?.name ?? fallbackName;
  const bar = useRef<HTMLElement>(null);

  // A stored "Less motion" choice takes effect on every public page, not only the home page.
  useEffect(() => {
    restoreLessMotion();
  }, []);

  // The bar gains a hairline once the page has scrolled under it.
  useEffect(() => {
    const el = bar.current;
    if (!el) return;
    const update = () => {
      el.dataset.scrolled = String(window.scrollY > 8);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  return (
    <div className="public-root min-h-screen bg-canvas text-ink">
      <div className="page-map" aria-hidden="true" />
      <a href="#main" className="skip-link">
        {t("app.skipToMain")}
      </a>
      <header ref={bar} className="pub-nav" data-scrolled="false">
        <div className="mx-auto flex max-w-[1200px] items-center gap-2 px-4 py-3">
          <a
            href="/"
            className="mr-auto inline-flex min-w-0 items-center gap-2.5 text-ink no-underline"
            aria-label={name}
          >
            <BrandLogo className="h-6 w-auto shrink-0" />
            <span className="display truncate text-[19px] font-semibold tracking-[-0.015em]">
              {name}
            </span>
          </a>
          <nav aria-label={copy.nav.label} className="hidden items-center gap-1 md:flex">
            {LINKS.map((link) => (
              <a key={link.href} href={link.href} className="pub-link">
                {link.label}
              </a>
            ))}
            <a href={REPO_URL} className="pub-link" rel="noopener">
              {copy.nav.github}
            </a>
          </nav>
          <details className="pub-menu relative md:hidden">
            <summary className="pub-link cursor-pointer list-none">{copy.nav.menu}</summary>
            <nav
              aria-label={copy.nav.label}
              className="card absolute right-0 z-10 mt-2 flex w-56 flex-col gap-1 p-2"
            >
              {LINKS.map((link) => (
                <a key={link.href} href={link.href} className="pub-link">
                  {link.label}
                </a>
              ))}
              <a href={REPO_URL} className="pub-link" rel="noopener">
                {copy.nav.github}
              </a>
            </nav>
          </details>
          <a
            href="/queue"
            data-testid="open-queue"
            aria-label={copy.nav.open}
            className="btn btn-primary ml-1 min-h-10! shrink-0 px-4! text-sm!"
          >
            <span className="max-[420px]:hidden">{copy.nav.open}</span>
            <span className="min-[421px]:hidden" aria-hidden="true">
              {copy.nav.openShort}
            </span>
          </a>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="outline-none">
        {children}
      </main>
      <footer className="border-t border-line bg-surface">
        <div className="mx-auto grid max-w-[1200px] gap-10 px-4 py-14 md:grid-cols-[5fr_3fr_3fr]">
          <div>
            <p className="display m-0 text-2xl text-ink">{name}</p>
            <p className="mt-3 mb-0 max-w-[34ch] text-ink-2" data-testid="public-footer">
              {t("public.footer")}
            </p>
            <p className="mt-6 mb-0 text-sm text-ink-2">{copy.footer.data}</p>
            <p className="mt-1 mb-0 text-sm text-ink-2">{copy.footer.usage}</p>
            <p className="mt-1 mb-0 text-sm text-ink-2">
              {copy.footer.licence}{" "}
              <a
                href={copy.footer.builtHref}
                rel="noopener noreferrer"
                className="underline underline-offset-4"
              >
                {copy.footer.built}
              </a>
            </p>
            <p className="mt-4 mb-0 max-w-[60ch] text-sm text-ink-2" data-testid="independence">
              {t("public.independence")}
            </p>
            <p className="mt-4 mb-0">
              <MotionSwitch />
            </p>
            <p className="mt-4 mb-0 text-sm font-medium text-ink" data-testid="made-by">
              <a
                href={copy.footer.madeByHref}
                rel="noopener noreferrer"
                className="underline underline-offset-4"
              >
                {copy.footer.madeBy}
              </a>
            </p>
            <p className="mt-2 mb-0 text-sm font-medium text-ink" data-testid="sponsor-link">
              <a
                href={copy.maker.links.sponsor}
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 underline underline-offset-4"
              >
                <Heart aria-hidden="true" size={14} strokeWidth={2} className="text-accent" />
                {copy.footer.sponsor}
              </a>
            </p>
          </div>
          <nav aria-label={copy.footer.label} className="flex flex-col gap-1">
            <p className="eyebrow m-0 mb-2">{copy.nav.label}</p>
            {LINKS.slice(0, 3).map((link) => (
              <a key={link.href} href={link.href} className={footerLink}>
                {link.label}
              </a>
            ))}
            <a href="/queue" className={footerLink}>
              {copy.nav.open}
            </a>
          </nav>
          <nav aria-label={`${copy.footer.label} project`} className="flex flex-col gap-1">
            <p className="eyebrow m-0 mb-2">{copy.footer.github}</p>
            <a href="/about" className={footerLink}>
              {copy.footer.about}
            </a>
            <a href="/docs/" className={footerLink}>
              {copy.footer.docs}
            </a>
            <a href="/privacy" className={footerLink}>
              {copy.footer.privacy}
            </a>
            <a href={REPO_URL} className={footerLink} rel="noopener">
              {copy.footer.github}
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
