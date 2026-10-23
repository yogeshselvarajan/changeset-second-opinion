import { useQuery } from "@tanstack/react-query";

import { getDraftOptions } from "../../api/@tanstack/react-query.gen";
import { requestDraft } from "../../api/sdk.gen";
import type { Response } from "../../api/types.gen";
import { t } from "../../i18n";
import type { FailureKind } from "../../lib/problem";
import { retryTransient } from "../case/failure";
import { callApi } from "../queue/queueQueries";

/** A generated draft, once its job has produced one. */
export function useDraft(draftId: string | null | undefined) {
  return useQuery({
    ...getDraftOptions({ path: { id: draftId ?? "" } }),
    enabled: Boolean(draftId),
    retry: retryTransient,
  });
}

export type DraftRequest =
  { ok: true; jobId: string } | { ok: false; message: string; kind: FailureKind };

/** Ask for a draft; the server answers 202 with a job id straight away and never waits. */
export async function startDraft(
  caseId: string,
  responseType: Response,
  regenerate: boolean,
): Promise<DraftRequest> {
  const outcome = await callApi(() =>
    requestDraft({
      path: { id: caseId },
      body: { response_type: responseType, regenerate },
      throwOnError: false,
    }),
  );
  if (outcome.ok) return { ok: true, jobId: outcome.data.job_id };
  const { failure, code } = outcome;
  if (failure.status === 409)
    return { ok: false, message: t("draft.request.notAllowed"), kind: failure.kind };
  if (failure.kind === "rate_limited" && code === "daily_cap_reached") {
    return { ok: false, message: t("draft.request.dailyCap"), kind: failure.kind };
  }
  return { ok: false, message: failure.message, kind: failure.kind };
}
