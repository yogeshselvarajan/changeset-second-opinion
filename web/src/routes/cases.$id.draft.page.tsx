import { DraftScreen } from "../components/draft/DraftScreen";
import { draftRoute } from "./cases.$id.draft";

export function DraftPage() {
  const { id } = draftRoute.useParams();
  return <DraftScreen id={id} />;
}
