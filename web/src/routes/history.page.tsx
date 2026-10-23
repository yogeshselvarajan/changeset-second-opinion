import { useNavigate } from "@tanstack/react-router";

import { HistoryScreen } from "../components/history/HistoryScreen";
import { historyRoute } from "./history";

export function HistoryPage() {
  const search = historyRoute.useSearch();
  const navigate = useNavigate({ from: "/history" });
  return <HistoryScreen filters={search} onFilters={(next) => void navigate({ search: next })} />;
}
