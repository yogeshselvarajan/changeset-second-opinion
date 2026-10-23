import type { Role } from "../../api/types.gen";
import { t } from "../../i18n";

const GLYPH: Record<Role, string> = { viewer: "○", reviewer: "●", admin: "◆" };

/** Who is signed in, as glyph plus text. No session at all reads "Not signed in". */
export function RoleBadge({
  userRole,
  name,
  viaOsm = false,
}: {
  userRole: Role | undefined;
  name?: string | null;
  /** The session came from signing in with OpenStreetMap, so the name is that account's. */
  viaOsm?: boolean;
}) {
  const label = userRole ? t(`role.${userRole}`) : t("role.signedOut");
  return (
    <span className="cso-pill" data-testid="role-badge" title={name ?? undefined}>
      <span aria-hidden="true">{userRole ? GLYPH[userRole] : "-"} </span>
      {label}
      {userRole === "viewer" ? (
        <span className="text-text-muted"> · {t("role.viewOnly")}</span>
      ) : null}
      {viaOsm && name ? (
        <span className="text-text-muted" data-testid="reviewing-as">
          {" "}
          · {t("role.reviewingAs", { name })}
        </span>
      ) : null}
    </span>
  );
}
