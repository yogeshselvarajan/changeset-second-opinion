import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";

import { listConfigVersionsOptions } from "../../api/@tanstack/react-query.gen";
import type { CommunityConfig } from "../../api/types.gen";
import { t } from "../../i18n";
import { formatDateTime } from "../case/caseModel";
import { failureFromError, retryTransient } from "../case/failure";
import { ScrollRegion } from "../case/ScrollRegion";
import { SectionSkeleton } from "../case/Section";
import { useConfig } from "../case/useCaseData";
import { copyText } from "../draft/clipboard";
import { controlClass } from "../queue/QueueDialog";
import { useAnnounce } from "../shell/Announcer";
import { redactFlaggedWords, toYaml } from "./configYaml";
import { PackSection } from "./PackSection";
import { ReliabilitySection } from "./ReliabilitySection";

function Block({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`${id}-title`} className="mt-5" data-testid={id}>
      <h2 id={`${id}-title`} className="text-base font-semibold">
        {title}
      </h2>
      <div className="mt-1 text-sm">{children}</div>
    </section>
  );
}

function Summary({ config }: { config: CommunityConfig }) {
  return (
    <>
      <Block id="config-version" title={t("config.version")}>
        <p className="font-mono break-all" data-testid="config-version-hash">
          {config.version}
        </p>
        <p className="text-text-muted">{t("config.version.note")}</p>
      </Block>
      <Block id="config-bands" title={t("config.bands")}>
        <ul className="list-disc pl-5">
          <li>{t("config.bands.confident", { value: config.bands.confident_min })}</li>
          <li>{t("config.bands.unsure", { value: config.bands.unsure_min })}</li>
          <li>
            {t("config.panel.thresholds", {
              low: config.panel.thresholds.low,
              high: config.panel.thresholds.high,
            })}
          </li>
        </ul>
      </Block>
      <Block id="config-rules" title={t("config.rules")}>
        <ul className="list-disc pl-5">
          {config.rules.map((rule) => (
            <li key={rule.code}>
              <span className="font-mono">{rule.code}</span> {rule.label}
            </li>
          ))}
        </ul>
      </Block>
      <Block id="config-tone" title={t("config.tone")}>
        <p>{t("config.tone.language", { language: config.tone.language_policy })}</p>
        <p className="mt-1">
          {config.tone.allowed_links.length > 0
            ? t("config.tone.links", { links: config.tone.allowed_links.join(", ") })
            : t("config.tone.noLinks")}
        </p>
        <p className="mt-1">
          {t("config.tone.flagged", { count: config.tone.banned_words.length })}
        </p>
      </Block>
    </>
  );
}

function Versions({ activeVersion }: { activeVersion: string }) {
  const versions = useQuery({ ...listConfigVersionsOptions(), retry: retryTransient });
  if (versions.isPending) return <SectionSkeleton label={t("config.versions.loading")} />;
  if (versions.isError) {
    return (
      <p role="alert" data-testid="config-versions-error">
        {failureFromError(versions.error).message}
      </p>
    );
  }
  const items = versions.data.items;
  if (items.length === 0) return <p>{t("config.versions.none")}</p>;
  return (
    <ScrollRegion label={t("config.versions.region")}>
      <table
        className="w-full min-w-[32rem] border-collapse text-left text-sm"
        data-testid="config-versions-table"
      >
        <caption className="sr-only">{t("config.versions.caption")}</caption>
        <thead>
          <tr className="border-b border-border text-text-muted">
            <th scope="col" className="py-1 pr-3 font-medium">
              {t("config.versions.col.version")}
            </th>
            <th scope="col" className="py-1 pr-3 font-medium">
              {t("config.versions.col.created")}
            </th>
            <th scope="col" className="py-1 font-medium">
              {t("config.versions.col.active")}
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.version}
              className="border-b border-border"
              data-active={item.version === activeVersion}
            >
              <th scope="row" className="py-1 pr-3 font-mono text-xs font-normal break-all">
                {item.version}
              </th>
              <td className="py-1 pr-3">{formatDateTime(item.created_at)}</td>
              <td className="py-1">
                {item.version === activeVersion ? t("config.versions.active") : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

/** `/config` for admins: the active community configuration, its YAML text, and the versions list. */
export function ConfigScreen() {
  const announce = useAnnounce();
  const config = useConfig();
  const yaml = useMemo(
    () => (config.data ? toYaml(redactFlaggedWords(config.data)) : ""),
    [config.data],
  );
  const lineNumbers = useMemo(() => {
    const count = yaml === "" ? 0 : yaml.split("\n").length - 1;
    return Array.from({ length: count }, (_, i) => String(i + 1)).join("\n");
  }, [yaml]);

  return (
    <section aria-labelledby="config-title" className="cso-page" data-testid="config-screen">
      <header className="cso-pagehead">
        <h1 id="config-title" className="text-xl font-semibold">
          {t("config.title")}
        </h1>
        <p className="mt-1 text-sm text-text-muted">{t("config.readOnly")}</p>
      </header>

      {config.isPending ? (
        <div className="mt-4">
          <SectionSkeleton label={t("config.loading")} />
        </div>
      ) : config.isError || !config.data ? (
        <div role="alert" className="mt-4" data-testid="config-error">
          <p>{failureFromError(config.error).message}</p>
          <button
            type="button"
            onClick={() => void config.refetch()}
            className={`${controlClass} mt-2`}
          >
            {t("app.retry")}
          </button>
        </div>
      ) : (
        <>
          <Summary config={config.data} />
          <Block id="config-packs" title={t("config.packs")}>
            <PackSection />
          </Block>
          <Block id="config-reliability" title={t("config.reliability")}>
            <ReliabilitySection />
          </Block>
          <Block id="config-yaml" title={t("config.yaml")}>
            <div className="mb-2 flex items-center gap-3">
              <button
                type="button"
                className={controlClass}
                onClick={async () => {
                  const ok = await copyText(yaml);
                  announce(t(ok ? "config.copied" : "config.copyFailed"));
                }}
                data-testid="config-copy"
              >
                {t("config.copy")}
              </button>
            </div>
            <ScrollRegion label={t("config.yaml.region")} className="rounded border border-border">
              <div className="flex font-mono text-xs leading-5">
                <pre
                  aria-hidden="true"
                  className="select-none border-r border-border px-2 text-right text-text-muted"
                >
                  {lineNumbers}
                </pre>
                <pre className="px-3" data-testid="config-yaml-text">
                  <code>{yaml}</code>
                </pre>
              </div>
            </ScrollRegion>
          </Block>
          <Block id="config-versions" title={t("config.versions")}>
            <Versions activeVersion={config.data.version} />
          </Block>
        </>
      )}
    </section>
  );
}
