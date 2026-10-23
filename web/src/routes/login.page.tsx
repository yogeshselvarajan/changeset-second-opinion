import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useRef, useState, type FormEvent } from "react";
import { FieldError, Input, Label, Text, TextField } from "react-aria-components";

import { meEndpointQueryKey } from "../api/@tanstack/react-query.gen";
import { loginEndpoint } from "../api/sdk.gen";
import { BrandLogo } from "../branding/BrandLogo";
import { useBranding } from "../branding/branding";
import { LivingMap } from "../landing/art/LivingMap";
import { useAnnounce } from "../components/shell/Announcer";
import { t } from "../i18n";
import { failureFromResponse, loginMessage, networkFailure, type Failure } from "../lib/problem";
import { canMutate, safeRedirect } from "../lib/roles";
import { useMe } from "../lib/useMe";
import { loginRoute } from "./login";

const inputClass =
  "mt-1 block min-h-10 w-full rounded-[var(--radius-control)] border border-control-border bg-surface px-3 text-text";

const OSM_ERRORS = ["denied", "expired", "failed", "busy", "not_allowed"] as const;

/** The sentence for `?osm_error=<code>`; unknown codes show nothing rather than echo the URL. */
function osmErrorMessage(code: string | undefined): string | null {
  const known = OSM_ERRORS.find((c) => c === code);
  return known ? t(`login.osm.error.${known}`) : null;
}

export function LoginPage() {
  const search = loginRoute.useSearch();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const { me } = useMe();
  const branding = useBranding();
  const formRef = useRef<HTMLFormElement>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [busy, setBusy] = useState(false);
  const osmError = osmErrorMessage(search.osm_error);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = {
      invite_code: String(form.get("invite_code") ?? ""),
      display_name: String(form.get("display_name") ?? "").trim(),
    };
    // The code lives only in this local object: it is cleared from the field right away and is
    // never put in state, storage, the URL or a log line.
    formRef.current?.reset();
    setBusy(true);
    setFailure(null);
    try {
      const result = await loginEndpoint({ body, throwOnError: false });
      const response = result.response;
      if (!response) {
        setFailure(networkFailure());
        return;
      }
      if (result.error !== undefined || !response.ok || !result.data) {
        setFailure(
          failureFromResponse(response.status, result.error, response.headers.get("Retry-After")),
        );
        return;
      }
      await queryClient.invalidateQueries({ queryKey: meEndpointQueryKey() });
      announce(t("login.success", { name: result.data.me.display_name ?? "" }));
      void navigate({ to: safeRedirect(search.redirect) });
    } catch {
      setFailure(networkFailure());
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-[calc(100vh-3rem)] min-[900px]:grid-cols-[55fr_45fr]">
      <aside
        aria-label={t("login.about")}
        className="relative flex flex-col justify-center gap-6 overflow-hidden border-b border-line bg-canvas p-6 min-[900px]:border-b-0 min-[900px]:border-r min-[900px]:p-12"
      >
        <div className="contours" aria-hidden="true" />
        <p className="relative m-0 flex items-center gap-2.5 font-display text-2xl font-semibold tracking-[-0.015em] text-ink">
          <BrandLogo className="h-7 w-auto" />
          <span data-testid="login-brand">{branding?.name ?? t("app.name")}</span>
        </p>
        <p className="display relative m-0 max-w-[22ch] text-[clamp(1.8rem,3.4vw,2.8rem)] text-ink">
          {branding?.tagline ?? t("login.tagline")}
        </p>
        <div className="relative max-w-xl">
          <LivingMap variant="compact" />
        </div>
      </aside>
      <section aria-labelledby="page-title" className="w-full max-w-md self-center p-6">
        <h1 id="page-title" className="text-xl font-semibold">
          {t("login.title")}
        </h1>
        <p className="mt-2 text-text-muted">{t("login.intro")}</p>

        {canMutate(me?.role) ? (
          <p className="mt-3" role="status">
            {t("login.alreadySignedIn", { name: me?.display_name ?? "" })}
          </p>
        ) : null}

        {osmError ? (
          <p
            role="alert"
            className="mt-3 rounded border border-border bg-surface p-3"
            data-testid="osm-error"
          >
            <span aria-hidden="true">⚠ </span>
            {osmError}
          </p>
        ) : null}

        {me?.osm_signin ? (
          <div className="mt-4">
            {/* A full page visit, not a fetch: the browser goes to OpenStreetMap and comes back. */}
            <a
              href="/api/v1/auth/osm/start"
              data-testid="osm-signin"
              className="btn btn-primary w-full"
            >
              {t("login.osm.button")}
            </a>
            <p className="mt-2 text-sm text-text-muted">{t("login.osm.help")}</p>
            <p className="mt-4 text-sm text-text-muted">{t("login.osm.or")}</p>
          </div>
        ) : null}

        <form
          ref={formRef}
          onSubmit={onSubmit}
          className="mt-4 flex flex-col gap-4"
          noValidate={false}
        >
          <TextField name="invite_code" isRequired type="password" autoComplete="off">
            <Label>{t("login.inviteCode")}</Label>
            <Input className={inputClass} spellCheck={false} maxLength={128} />
            <FieldError className="text-sm" />
          </TextField>

          <TextField name="display_name" isRequired autoComplete="nickname">
            <Label>{t("login.displayName")}</Label>
            <Input className={inputClass} maxLength={80} />
            <Text slot="description" className="text-text-muted">
              {t("login.displayNameHelp")}
            </Text>
            <FieldError className="text-sm" />
          </TextField>

          {failure ? (
            <p
              role="alert"
              className="rounded border border-border bg-surface p-3"
              data-testid="login-error"
            >
              <span aria-hidden="true">⚠ </span>
              {loginMessage(failure)}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={busy}
            className="btn btn-primary w-full disabled:opacity-60"
          >
            {busy ? t("login.submitting") : t("login.submit")}
          </button>
        </form>
        <p className="mt-6 mb-0 text-sm text-ink-2" data-testid="independence">
          {t("public.independence")}
        </p>
        {me?.mode === "replay" ? (
          <p className="mt-4">
            <Link to="/queue" search={{}} className="text-ink-2 underline underline-offset-4">
              {t("login.browse")}
            </Link>
          </p>
        ) : null}
      </section>
    </div>
  );
}
