import { Tab, TabList, TabPanel, Tabs } from "react-aria-components";

import { t } from "../../i18n";
import { failureFromError } from "../case/failure";
import { SectionSkeleton } from "../case/Section";
import { controlClass } from "../queue/QueueDialog";
import { AccessTab } from "./AccessTab";
import { ExportTab } from "./ExportTab";
import { ReviewTab } from "./ReviewTab";
import { WorkspaceTab } from "./WorkspaceTab";
import { useSettings } from "./useSettings";

const tabClass =
  "min-h-9 cursor-pointer border-b-2 border-transparent px-3 py-1.5 text-ink-2 outline-none data-focus-visible:outline-2 data-focus-visible:outline-offset-2 data-focus-visible:outline-[var(--color-focus)] data-selected:border-accent data-selected:font-medium data-selected:text-ink";

const TABS = ["workspace", "review", "access", "export"] as const;

/** `/settings` for admins: four tabs over one settings record that is saved with `If-Match`. */
export function SettingsScreen() {
  const settings = useSettings();
  const data = settings.data;
  // After a reload the form is built again from the server's version.
  const reload = () => void settings.refetch();

  return (
    <section aria-labelledby="settings-title" className="cso-page" data-testid="settings-screen">
      <header className="cso-pagehead">
        <h1 id="settings-title" className="text-xl font-semibold">
          {t("settings.title")}
        </h1>
        <p className="mt-1 mb-0 text-sm text-ink-2">{t("settings.intro")}</p>
      </header>

      {settings.isPending ? (
        <div className="mt-4">
          <SectionSkeleton label={t("settings.loading")} />
        </div>
      ) : settings.isError || !data ? (
        <div role="alert" className="mt-4" data-testid="settings-error">
          <p>{failureFromError(settings.error).message}</p>
          <button type="button" className={`${controlClass} mt-2`} onClick={reload}>
            {t("app.retry")}
          </button>
        </div>
      ) : (
        <Tabs className="mt-3" defaultSelectedKey="workspace">
          <TabList
            aria-label={t("settings.tabs.label")}
            className="flex flex-wrap gap-1 border-b border-line"
          >
            {TABS.map((id) => (
              <Tab key={id} id={id} className={tabClass} data-testid={`tab-${id}`}>
                {t(`settings.tab.${id}`)}
              </Tab>
            ))}
          </TabList>
          {/* `key` rebuilds a form from the server's values whenever the version moves. */}
          <TabPanel id="workspace" className="outline-none">
            <WorkspaceTab key={data.version} settings={data} onReload={reload} />
          </TabPanel>
          <TabPanel id="review" className="outline-none">
            <ReviewTab settings={data} />
          </TabPanel>
          <TabPanel id="access" className="outline-none">
            <AccessTab settings={data} onReload={reload} />
          </TabPanel>
          <TabPanel id="export" className="outline-none">
            <ExportTab settings={data} />
          </TabPanel>
        </Tabs>
      )}
    </section>
  );
}
