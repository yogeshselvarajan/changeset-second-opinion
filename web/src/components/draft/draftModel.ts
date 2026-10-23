import type { Disposition, DraftStatus } from "../../api/types.gen";
import { t, type MessageKey } from "../../i18n";
import type { CheckId } from "./draftChecks";

/** Why a draft job can end without a draft; the server sends one of these short codes. */
const FAILURE_KEYS: Record<string, MessageKey> = {
  draft_not_available: "draft.fail.draft_not_available",
  draft_not_allowed: "draft.fail.draft_not_allowed",
  draft_run_stale: "draft.fail.draft_run_stale",
  draft_run_missing: "draft.fail.draft_run_missing",
  draft_response_invalid: "draft.fail.draft_response_invalid",
  draft_not_produced: "draft.fail.draft_not_produced",
  draft_invalid: "draft.fail.draft_invalid",
};

export function draftFailureMessage(code: string | null | undefined): string {
  const key = code ? FAILURE_KEYS[code] : undefined;
  return t(key ?? "draft.fail.unknown");
}

/** The server's violation codes, each with a plain sentence that never repeats the offending text. */
const VIOLATION_KEYS: Record<string, MessageKey> = {
  model_unable: "draft.violation.model_unable",
  empty_greeting: "draft.violation.empty_greeting",
  empty_body: "draft.violation.empty_body",
  greeting_too_long: "draft.violation.greeting_too_long",
  closing_too_long: "draft.violation.closing_too_long",
  body_too_long: "draft.violation.body_too_long",
  too_many_words: "draft.violation.too_many_words",
  banned_word: "draft.violation.banned_word",
  accusatory_language: "draft.violation.accusatory_language",
  instruction_like_text: "draft.violation.instruction_like_text",
  markup: "draft.violation.markup",
  disallowed_url: "draft.violation.disallowed_url",
  uncited: "draft.violation.uncited",
  too_many_citations: "draft.violation.too_many_citations",
  unknown_evidence_id: "draft.violation.unknown_evidence_id",
  ungrounded_number: "draft.violation.ungrounded_number",
  ungrounded_quote: "draft.violation.ungrounded_quote",
  copied_text: "draft.violation.copied_text",
  language_mismatch: "draft.violation.language_mismatch",
};

export function violationMessage(code: string): string {
  const key = VIOLATION_KEYS[code];
  return key ? t(key) : t("draft.violation.unknown");
}

export const CHECK_LABEL: Record<CheckId, MessageKey> = {
  present: "draft.check.present",
  length: "draft.check.length",
  avoidList: "draft.check.avoidList",
  tone: "draft.check.tone",
  markup: "draft.check.markup",
  links: "draft.check.links",
  language: "draft.check.language",
  question: "draft.check.question",
};

export const DRAFT_STATUS_LABEL: Record<DraftStatus, MessageKey> = {
  generated: "draft.status.generated",
  validated: "draft.status.validated",
  rejected_by_validator: "draft.status.rejected_by_validator",
  template_fallback: "draft.status.template_fallback",
};

/** Plain-language names for dispositions, shared with the queue's outcome column. */
export const DISPOSITION_LABEL: Record<Disposition, MessageKey> = {
  agree: "queue.outcome.agree",
  different_response: "queue.outcome.different_response",
  needs_survey: "queue.outcome.needs_survey",
  disagree_with_model: "queue.outcome.disagree_with_model",
  no_action: "queue.outcome.no_action",
};

export function dispositionLabel(value: string | null | undefined): string {
  if (!value) return t("case.unknown");
  const key = DISPOSITION_LABEL[value as Disposition];
  return key ? t(key) : value;
}

/** True when a draft was made without a model (template wording, or the validator replaced it). */
export function isTemplateDraft(status: DraftStatus, modelId: string | null | undefined): boolean {
  return status === "template_fallback" || !modelId;
}

/** Where an edited, not yet recorded, draft is kept for this browser tab, so Back does not lose it. */
export function editStorageKey(draftId: string): string {
  return `cso.draft.edit.${draftId}`;
}
