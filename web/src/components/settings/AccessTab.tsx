import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  createInviteCodeMutation,
  listInvitesOptions,
  listInvitesQueryKey,
  revokeInviteMutation,
} from "../../api/@tanstack/react-query.gen";
import type { InviteOut, Role, WorkspaceSettings } from "../../api/types.gen";
import { t } from "../../i18n";
import { formatDateTime } from "../case/caseModel";
import { failureFromError, retryTransient } from "../case/failure";
import { ScrollRegion } from "../case/ScrollRegion";
import { SectionSkeleton } from "../case/Section";
import { copyText } from "../draft/clipboard";
import { controlClass, QueueDialog } from "../queue/QueueDialog";
import { useAnnounce } from "../shell/Announcer";
import { ConflictNotice, Field, Panel, inputClass } from "./parts";
import { LABEL_MAX, usesLabel } from "./settingsModel";
import { useSaveSettings } from "./useSettings";

/** An empty box means "no limit"; anything else must be a whole number of at least one. */
function optionalCount(value: string): number | null | undefined {
  const text = value.trim();
  if (text === "") return null;
  const n = Number(text);
  return Number.isInteger(n) && n >= 1 ? n : undefined;
}

function SignInSwitch({
  settings,
  onReload,
}: {
  settings: WorkspaceSettings;
  onReload: () => void;
}) {
  const announce = useAnnounce();
  const { save, isSaving } = useSaveSettings(settings);
  const [conflict, setConflict] = useState(false);
  const [failed, setFailed] = useState(false);
  const configured = settings.osm_signin_configured;

  async function change(next: boolean) {
    setConflict(false);
    setFailed(false);
    const result = await save({ osm_signin_enabled: next });
    if (result.ok) {
      announce(
        t("settings.access.signin.saved", {
          state: t(next ? "settings.access.signin.on" : "settings.access.signin.off"),
        }),
      );
    } else if (result.kind === "conflict") setConflict(true);
    else setFailed(true);
  }

  return (
    <Panel id="settings-signin" title={t("settings.access.signin")}>
      <div className="mt-3 max-w-xl">
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            className="mt-1"
            checked={settings.osm_signin_enabled && configured}
            disabled={!configured || isSaving}
            aria-describedby="signin-help signin-reason"
            onChange={(event) => void change(event.target.checked)}
            data-testid="signin-toggle"
          />
          <span>{t("settings.access.signin.label")}</span>
        </label>
        <p id="signin-help" className="mt-1 mb-0 text-sm text-ink-2">
          {t("settings.access.signin.help")}
        </p>
        <p id="signin-reason" className="mt-1 mb-0 text-sm" data-testid="signin-reason">
          {configured ? "" : t("settings.access.signin.unavailable")}
        </p>
        {conflict ? <ConflictNotice onReload={onReload} /> : null}
        {failed ? (
          <p role="alert" className="mt-2 mb-0">
            <span aria-hidden="true">⚠ </span>
            {t("api.error.generic")}
          </p>
        ) : null}
      </div>
    </Panel>
  );
}

function CreateDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const [label, setLabel] = useState("");
  const [role, setRole] = useState<Role>("reviewer");
  const [ttl, setTtl] = useState("");
  const [uses, setUses] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const create = useMutation({
    ...createInviteCodeMutation(),
    onSuccess: async (created) => {
      setCode(created.code);
      await queryClient.invalidateQueries({ queryKey: listInvitesQueryKey() });
    },
    onError: () => setError(t("settings.access.create.error")),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const ttlHours = optionalCount(ttl);
    const maxUses = optionalCount(uses);
    if (ttlHours === undefined || maxUses === undefined || label.length > LABEL_MAX) {
      setError(t("settings.access.create.error"));
      return;
    }
    setError(null);
    create.mutate({ body: { label: label.trim(), role, ttl_hours: ttlHours, max_uses: maxUses } });
  }

  if (code !== null) {
    return (
      <QueueDialog
        isOpen
        onOpenChange={(open) => (open ? undefined : onClose())}
        title={t("settings.access.code.title")}
      >
        <p className="mt-2">{t("settings.access.code.body")}</p>
        <p
          className="mt-2 mb-0 rounded-[var(--radius-control)] border border-line bg-canvas p-2 font-mono break-all select-all"
          data-testid="invite-code"
        >
          {code}
        </p>
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            className={controlClass}
            data-testid="invite-copy"
            onClick={async () =>
              announce(
                t(
                  (await copyText(code))
                    ? "settings.access.code.copied"
                    : "settings.access.code.copyFailed",
                ),
              )
            }
          >
            {t("settings.access.code.copy")}
          </button>
          <button
            type="button"
            className={controlClass}
            onClick={onClose}
            data-testid="invite-done"
          >
            {t("settings.access.code.done")}
          </button>
        </div>
      </QueueDialog>
    );
  }

  return (
    <QueueDialog
      isOpen
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={t("settings.access.create.title")}
    >
      <form onSubmit={submit} noValidate>
        <Field
          id="invite-label"
          label={t("settings.access.create.label")}
          hint={t("settings.access.create.label.hint", { max: LABEL_MAX })}
        >
          {(props) => (
            <input
              {...props}
              type="text"
              value={label}
              maxLength={LABEL_MAX}
              onChange={(event) => setLabel(event.target.value)}
              className={inputClass}
              autoComplete="off"
              data-testid="invite-label"
            />
          )}
        </Field>
        <Field id="invite-role" label={t("settings.access.create.role")}>
          {(props) => (
            <select
              {...props}
              value={role}
              onChange={(event) => setRole(event.target.value as Role)}
              className={inputClass}
              data-testid="invite-role"
            >
              <option value="reviewer">{t("role.reviewer")}</option>
              <option value="admin">{t("role.admin")}</option>
            </select>
          )}
        </Field>
        <Field
          id="invite-ttl"
          label={t("settings.access.create.ttl")}
          hint={t("settings.access.create.ttl.hint")}
        >
          {(props) => (
            <input
              {...props}
              type="number"
              min={1}
              inputMode="numeric"
              value={ttl}
              onChange={(event) => setTtl(event.target.value)}
              className={inputClass}
              data-testid="invite-ttl"
            />
          )}
        </Field>
        <Field
          id="invite-uses"
          label={t("settings.access.create.uses")}
          hint={t("settings.access.create.uses.hint")}
        >
          {(props) => (
            <input
              {...props}
              type="number"
              min={1}
              inputMode="numeric"
              value={uses}
              onChange={(event) => setUses(event.target.value)}
              className={inputClass}
              data-testid="invite-uses"
            />
          )}
        </Field>
        {error ? (
          <p role="alert" className="mt-3 mb-0" data-testid="invite-error">
            <span aria-hidden="true">⚠ </span>
            {error}
          </p>
        ) : null}
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <button type="button" className={controlClass} onClick={onClose}>
            {t("settings.access.cancel")}
          </button>
          <button
            type="submit"
            className={controlClass}
            disabled={create.isPending}
            data-testid="invite-submit"
          >
            {t("settings.access.create.submit")}
          </button>
        </div>
      </form>
    </QueueDialog>
  );
}

function RevokeDialog({ invite, onClose }: { invite: InviteOut; onClose: () => void }) {
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const [error, setError] = useState<string | null>(null);
  const revoke = useMutation({
    ...revokeInviteMutation(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: listInvitesQueryKey() });
      announce(t("settings.access.revoked"));
      onClose();
    },
    onError: (failure) => setError(failureFromError(failure).message),
  });
  return (
    <QueueDialog
      isOpen
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={t("settings.access.revoke.title")}
    >
      <p className="mt-2">{t("settings.access.revoke.body")}</p>
      <p className="mt-1 mb-0 font-medium">{invite.label || t("settings.access.unlabelled")}</p>
      {error ? (
        <p role="alert" className="mt-2 mb-0">
          {error}
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <button type="button" className={controlClass} onClick={onClose}>
          {t("settings.access.cancel")}
        </button>
        <button
          type="button"
          className={controlClass}
          disabled={revoke.isPending}
          onClick={() => revoke.mutate({ path: { id: invite.id } })}
          data-testid="revoke-confirm"
        >
          {t("settings.access.revoke.confirm")}
        </button>
      </div>
    </QueueDialog>
  );
}

function InviteTable() {
  const invites = useQuery({ ...listInvitesOptions(), retry: retryTransient });
  const [revoking, setRevoking] = useState<InviteOut | null>(null);

  if (invites.isPending) return <SectionSkeleton label={t("settings.access.invites.loading")} />;
  if (invites.isError || !invites.data) {
    return (
      <p role="alert" data-testid="invites-error">
        {t("settings.access.invites.error")}
      </p>
    );
  }
  const items = invites.data.items;
  if (items.length === 0)
    return <p data-testid="invites-none">{t("settings.access.invites.none")}</p>;

  return (
    <>
      <ScrollRegion label={t("settings.access.invites.region")}>
        <table
          className="w-full min-w-[40rem] border-collapse text-left text-sm"
          data-testid="invite-table"
        >
          <caption className="sr-only">{t("settings.access.invites.caption")}</caption>
          <thead>
            <tr className="border-b border-line text-ink-2">
              {(["label", "role", "created", "expires", "uses", "status", "actions"] as const).map(
                (column) => (
                  <th key={column} scope="col" className="py-1 pr-3 font-medium">
                    {t(`settings.access.col.${column}`)}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {items.map((invite) => (
              <tr
                key={invite.id}
                className="border-b border-line align-top"
                data-status={invite.status}
              >
                <th scope="row" className="py-1 pr-3 font-normal">
                  {invite.label || t("settings.access.unlabelled")}
                </th>
                <td className="py-1 pr-3">{t(`role.${invite.role}`)}</td>
                <td className="py-1 pr-3">{formatDateTime(invite.created_at)}</td>
                <td className="py-1 pr-3">
                  {invite.expires_at
                    ? formatDateTime(invite.expires_at)
                    : t("settings.access.never")}
                </td>
                <td className="py-1 pr-3">{usesLabel(invite.use_count, invite.max_uses)}</td>
                <td className="py-1 pr-3" data-testid="invite-status">
                  {t(`settings.access.status.${invite.status}`)}
                </td>
                <td className="py-1">
                  {invite.status === "revoked" ? null : (
                    <button
                      type="button"
                      className={controlClass}
                      onClick={() => setRevoking(invite)}
                      data-testid="invite-revoke"
                    >
                      {t("settings.access.revoke")}
                      <span className="sr-only">
                        {" "}
                        {invite.label || t("settings.access.unlabelled")}
                      </span>
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>
      {revoking ? <RevokeDialog invite={revoking} onClose={() => setRevoking(null)} /> : null}
    </>
  );
}

/** Who may sign in: the OpenStreetMap switch and the invite codes. */
export function AccessTab({
  settings,
  onReload,
}: {
  settings: WorkspaceSettings;
  onReload: () => void;
}) {
  const [creating, setCreating] = useState(false);
  return (
    <>
      <SignInSwitch settings={settings} onReload={onReload} />
      <Panel id="settings-invites" title={t("settings.access.invites")}>
        <p className="mt-3 mb-3">
          <button
            type="button"
            className={controlClass}
            onClick={() => setCreating(true)}
            data-testid="invite-create"
          >
            {t("settings.access.create")}
          </button>
        </p>
        <InviteTable />
        {creating ? <CreateDialog onClose={() => setCreating(false)} /> : null}
      </Panel>
    </>
  );
}
