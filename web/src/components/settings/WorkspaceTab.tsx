import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";

import type { WorkspaceSettings } from "../../api/types.gen";
import { accentReadout, isHexColour } from "../../branding/contrast";
import { t } from "../../i18n";
import { controlClass } from "../queue/QueueDialog";
import { useAnnounce } from "../shell/Announcer";
import { ConflictNotice, Field, Panel, inputClass } from "./parts";
import {
  LOGO_MAX_BYTES,
  NAME_MAX,
  PARAGRAPH_MAX,
  TAGLINE_MAX,
  fieldLabel,
  isDirty,
  readLogoFile,
  svgDataUrl,
  type SettingsEdit,
} from "./settingsModel";
import { useSaveSettings } from "./useSettings";

const primaryClass =
  "min-h-9 rounded-[var(--radius-control)] bg-accent px-4 text-accent-fg disabled:opacity-60";

function AccentReadout({ value }: { value: string }) {
  const readout = accentReadout(value);
  if (!readout) {
    return (
      <p className="m-0 text-sm text-ink-2" data-testid="accent-readout">
        {t("settings.ws.contrast.invalid")}
      </p>
    );
  }
  return (
    <div className="text-sm" data-testid="accent-readout">
      <p className="m-0" data-testid="accent-light" data-passes={readout.passes}>
        {readout.passes ? "✓ " : "⚠ "}
        {t("settings.ws.contrast.light", {
          ratio: readout.light.toFixed(2),
          verdict: t(readout.passes ? "settings.ws.contrast.enough" : "settings.ws.contrast.low"),
        })}
      </p>
      <p className="m-0 mt-0.5 text-ink-2" data-testid="accent-dark">
        {t("settings.ws.contrast.dark", {
          hex: readout.darkHex,
          ratio: readout.dark.toFixed(2),
        })}
      </p>
    </div>
  );
}

/** Name, tagline, accent, logo and the community paragraph, saved together with `If-Match`. */
export function WorkspaceTab({
  settings,
  onReload,
}: {
  settings: WorkspaceSettings;
  onReload: () => void;
}) {
  const announce = useAnnounce();
  const { save, isSaving } = useSaveSettings(settings);
  const [draft, setDraft] = useState<SettingsEdit>({
    name: settings.name,
    tagline: settings.tagline,
    accent_hex: settings.accent_hex,
    community_paragraph: settings.community_paragraph,
    logo_svg: settings.logo_svg ?? null,
    osm_signin_enabled: settings.osm_signin_enabled,
  });
  const [logoNote, setLogoNote] = useState<string | null>(null);
  const [problems, setProblems] = useState<Record<string, string[]>>({});
  const [conflict, setConflict] = useState(false);
  const [failed, setFailed] = useState(false);
  const [refusals, setRefusals] = useState(0);
  const summary = useRef<HTMLDivElement>(null);

  // After each refused save, move to the list so a keyboard or screen reader user lands on what
  // needs attention.
  useEffect(() => {
    if (refusals > 0) summary.current?.focus();
  }, [refusals]);

  const dirty = isDirty(settings, draft);
  const set = <K extends keyof SettingsEdit>(key: K, value: SettingsEdit[K]) =>
    setDraft((previous) => ({ ...previous, [key]: value }));
  const problemFields = Object.keys(problems);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!dirty || isSaving) return;
    setProblems({});
    setConflict(false);
    setFailed(false);
    const result = await save(draft);
    if (result.ok) {
      announce(t("settings.saved"));
      return;
    }
    if (result.kind === "conflict") setConflict(true);
    else if (result.kind === "invalid") {
      setProblems(result.fields);
      setRefusals((count) => count + 1);
    } else setFailed(true);
  }

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const read = await readLogoFile(file);
    if (!read.ok) {
      const kb = LOGO_MAX_BYTES / 1024;
      setLogoNote(
        read.reason === "tooBig"
          ? t("settings.ws.logo.tooBig", { kb })
          : t(read.reason === "notSvg" ? "settings.ws.logo.notSvg" : "settings.ws.logo.unreadable"),
      );
      return;
    }
    set("logo_svg", read.svg);
    setLogoNote(t("settings.ws.logo.chosen", { file: file.name }));
  }

  function removeLogo() {
    set("logo_svg", null);
    setLogoNote(t("settings.ws.logo.removed"));
  }

  const swatch = isHexColour(draft.accent_hex) ? draft.accent_hex : "transparent";

  return (
    <form
      onSubmit={onSubmit}
      noValidate
      aria-label={t("settings.tab.workspace")}
      className="max-w-xl"
    >
      <Panel id="settings-workspace" title={t("settings.tab.workspace")}>
        {problemFields.length > 0 ? (
          <div
            ref={summary}
            tabIndex={-1}
            role="alert"
            className="mt-3 rounded-[var(--radius-pane)] border border-control-border bg-surface p-3 outline-none"
            data-testid="settings-problems"
          >
            <p className="m-0 font-medium">{t("settings.problems")}</p>
            <ul className="m-0 mt-1 list-disc pl-5 text-sm">
              {problemFields.map((field) => (
                <li key={field}>
                  <button
                    type="button"
                    className="inline-flex min-h-6 cursor-pointer items-center underline"
                    onClick={() => document.getElementById(`ws-${field}`)?.focus()}
                  >
                    {fieldLabel(field)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {conflict ? <ConflictNotice onReload={onReload} /> : null}
        {failed ? (
          <p role="alert" className="mt-3" data-testid="settings-failed">
            <span aria-hidden="true">⚠ </span>
            {t("api.error.generic")}
          </p>
        ) : null}

        <Field
          id="ws-name"
          label={t("settings.ws.name")}
          hint={t("settings.ws.name.hint", { max: NAME_MAX })}
          errors={problems.name}
        >
          {(props) => (
            <input
              {...props}
              type="text"
              value={draft.name}
              onChange={(event) => set("name", event.target.value)}
              className={inputClass}
              autoComplete="off"
            />
          )}
        </Field>

        <Field
          id="ws-tagline"
          label={t("settings.ws.tagline")}
          hint={t("settings.ws.tagline.hint", { max: TAGLINE_MAX })}
          errors={problems.tagline}
        >
          {(props) => (
            <input
              {...props}
              type="text"
              value={draft.tagline}
              onChange={(event) => set("tagline", event.target.value)}
              className={inputClass}
              autoComplete="off"
            />
          )}
        </Field>

        <Field
          id="ws-accent_hex"
          label={t("settings.ws.accent")}
          hint={t("settings.ws.accent.hint")}
          errors={problems.accent_hex}
        >
          {(props) => (
            <div className="flex items-center gap-2">
              <input
                {...props}
                type="text"
                value={draft.accent_hex}
                onChange={(event) => set("accent_hex", event.target.value.trim())}
                className={`${inputClass} max-w-[10rem] font-mono`}
                autoComplete="off"
                spellCheck={false}
                maxLength={7}
              />
              <span
                role="img"
                aria-label={t("settings.ws.accent.swatch")}
                className="mt-1 inline-block size-9 shrink-0 rounded-[var(--radius-control)] border border-control-border"
                style={{ background: swatch }}
                data-testid="accent-swatch"
              />
            </div>
          )}
        </Field>
        <div className="mt-2" aria-live="polite">
          <AccentReadout value={draft.accent_hex} />
        </div>

        <Field
          id="ws-logo_svg"
          label={t("settings.ws.logo")}
          hint={t("settings.ws.logo.hint", { kb: LOGO_MAX_BYTES / 1024 })}
          errors={problems.logo_svg}
        >
          {(props) => (
            <div className="mt-1 flex flex-wrap items-center gap-3">
              {draft.logo_svg ? (
                <img
                  src={svgDataUrl(draft.logo_svg)}
                  alt={t("settings.ws.logo.current")}
                  className="h-10 w-auto max-w-[8rem] rounded-[var(--radius-control)] border border-line bg-canvas p-1"
                  data-testid="logo-preview"
                />
              ) : (
                <span className="text-sm text-ink-2" data-testid="logo-none">
                  {t("settings.ws.logo.none")}
                </span>
              )}
              <input
                {...props}
                type="file"
                accept="image/svg+xml,.svg"
                onChange={(event) => void onFile(event)}
                className="max-w-full text-sm"
                data-testid="logo-file"
              />
              {draft.logo_svg ? (
                <button
                  type="button"
                  className={controlClass}
                  onClick={removeLogo}
                  data-testid="logo-remove"
                >
                  {t("settings.ws.logo.remove")}
                </button>
              ) : null}
            </div>
          )}
        </Field>
        {logoNote ? (
          <p role="status" className="mt-1 mb-0 text-sm" data-testid="logo-note">
            {logoNote}
          </p>
        ) : null}

        <Field
          id="ws-community_paragraph"
          label={t("settings.ws.paragraph")}
          hint={t("settings.ws.paragraph.hint", { max: PARAGRAPH_MAX })}
          errors={problems.community_paragraph}
        >
          {(props) => (
            <textarea
              {...props}
              rows={5}
              value={draft.community_paragraph}
              onChange={(event) => set("community_paragraph", event.target.value)}
              className={`${inputClass} py-2`}
            />
          )}
        </Field>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button
            type="submit"
            className={primaryClass}
            disabled={!dirty || isSaving}
            data-testid="settings-save"
          >
            {isSaving ? t("settings.saving") : t("settings.save")}
          </button>
          <button
            type="button"
            className={controlClass}
            disabled={!dirty || isSaving}
            onClick={() => {
              setDraft({
                name: settings.name,
                tagline: settings.tagline,
                accent_hex: settings.accent_hex,
                community_paragraph: settings.community_paragraph,
                logo_svg: settings.logo_svg ?? null,
                osm_signin_enabled: settings.osm_signin_enabled,
              });
              setProblems({});
              setLogoNote(null);
            }}
            data-testid="settings-discard"
          >
            {t("settings.discard")}
          </button>
          {dirty ? (
            <span className="text-sm text-ink-2" role="status" data-testid="settings-unsaved">
              {t("settings.unsaved")}
            </span>
          ) : null}
        </div>
      </Panel>
    </form>
  );
}
