import { CaseDetailView } from "../components/case/CaseDetailView";
import { caseRoute } from "./cases.$id";

/** The key resets the screen's own state (map, notices) when next and previous move between cases. */
export function CasePage() {
  const { id } = caseRoute.useParams();
  return <CaseDetailView id={id} key={id} />;
}
