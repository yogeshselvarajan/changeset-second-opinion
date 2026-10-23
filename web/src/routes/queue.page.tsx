import { useNavigate } from "@tanstack/react-router";

import { QueueScreen } from "../components/queue/QueueScreen";
import { queueRoute } from "./queue";

export function QueueRoute() {
  const search = queueRoute.useSearch();
  const navigate = useNavigate({ from: "/queue" });
  // Filters replace the history entry, so the back button leaves the queue instead of stepping
  // through every keystroke of a search.
  return (
    <QueueScreen
      search={search}
      onSearch={(next) => void navigate({ to: "/queue", search: next, replace: true })}
    />
  );
}
