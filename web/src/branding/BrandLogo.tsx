import { Mark } from "../landing/Mark";
import { LOGO_URL, useBranding } from "./branding";

/**
 * The logo for the top of a page: the workspace's own when it has one, otherwise the built-in mark.
 * The uploaded file is shown through an `img` tag, which never runs anything inside an SVG, and
 * the server serves it with a sandboxing policy as well.
 */
export function BrandLogo({ className = "h-5 w-auto" }: { className?: string }) {
  const branding = useBranding();
  if (branding?.has_logo) {
    return <img src={LOGO_URL} alt="" width={20} height={20} className={className} />;
  }
  return <Mark className={className} />;
}
