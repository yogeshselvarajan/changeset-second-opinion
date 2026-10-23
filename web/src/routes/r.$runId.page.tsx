import { useQuery } from "@tanstack/react-query";

import { getReceiptOptions } from "../api/@tanstack/react-query.gen";
import { SectionSkeleton } from "../components/case/Section";
import { ReceiptView } from "../components/receipt/ReceiptView";
import { t } from "../i18n";
import { Seo } from "../seo/Seo";
import { receiptRoute } from "./r.$runId";

export function ReceiptPage() {
  const { runId } = receiptRoute.useParams();
  const query = useQuery({ ...getReceiptOptions({ path: { run_id: runId } }), retry: false });
  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <ReceiptBody pending={query.isPending} data={query.isError ? undefined : query.data} />
    </div>
  );
}

function ReceiptBody({
  pending,
  data,
}: {
  pending: boolean;
  data: Parameters<typeof ReceiptView>[0]["receipt"] | undefined;
}) {
  if (pending) {
    return (
      <>
        <Seo title={t("receipt.seo.loading")} robots="noindex,follow" />
        <SectionSkeleton label={t("receipt.loading")} />
      </>
    );
  }
  if (!data) {
    return (
      <section aria-labelledby="receipt-title" data-testid="receipt-missing">
        <Seo title={t("receipt.missing.title")} robots="noindex" />
        <h1 id="receipt-title" className="text-xl font-semibold">
          {t("receipt.missing.title")}
        </h1>
        <p className="mt-2 text-ink-2">{t("receipt.missing.body")}</p>
      </section>
    );
  }
  return (
    <>
      <Seo
        title={t("receipt.seo.title", { id: data.changeset_id })}
        description={t("receipt.seo.description", { id: data.changeset_id })}
        robots="noindex,follow"
      />
      <ReceiptView receipt={data} />
    </>
  );
}
