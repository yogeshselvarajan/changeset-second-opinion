import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LANES } from "../../lib/lanes";
import { t } from "../../i18n";
import { LaneChip } from "./LaneChip";
import { HostedViewOnly, ModeBadge, ModeBanner } from "./ModeBanner";
import { RoleBadge } from "./RoleBadge";

describe("ModeBanner", () => {
  it("explains replay mode in text", () => {
    render(<ModeBanner mode="replay" />);
    expect(screen.getByTestId("replay-banner")).toHaveTextContent(t("mode.replayBanner"));
  });

  it("says nothing about view only on a copy that people run themselves", () => {
    render(<ModeBanner mode="replay" />);
    expect(screen.queryByTestId("hosted-view-only")).toBeNull();
  });

  it("links the hosted demo sentence to the self host guide", () => {
    render(<HostedViewOnly />);
    expect(screen.getByTestId("hosted-view-only")).toHaveTextContent(
      "This hosted demo is view only",
    );
    expect(screen.getByRole("link", { name: t("mode.hostedGuide") })).toHaveAttribute(
      "href",
      "/docs/self-host/docker-compose/",
    );
  });

  it("is absent in live mode and while the mode is unknown", () => {
    const { rerender } = render(<ModeBanner mode="live" />);
    expect(screen.queryByTestId("replay-banner")).toBeNull();
    rerender(<ModeBanner mode={undefined} />);
    expect(screen.queryByTestId("replay-banner")).toBeNull();
  });
});

describe("ModeBadge", () => {
  it("carries text as well as a glyph", () => {
    const { rerender } = render(<ModeBadge mode="replay" />);
    expect(screen.getByTestId("mode-badge")).toHaveTextContent("Demo");
    rerender(<ModeBadge mode="live" />);
    expect(screen.getByTestId("mode-badge")).toHaveTextContent("Live");
    rerender(<ModeBadge mode={undefined} />);
    expect(screen.getByText(t("mode.unknown"))).toBeInTheDocument();
  });
});

describe("RoleBadge", () => {
  it("shows the role as text and marks viewers as view only", () => {
    const { rerender } = render(<RoleBadge userRole="viewer" />);
    expect(screen.getByTestId("role-badge")).toHaveTextContent("Viewer");
    expect(screen.getByTestId("role-badge")).toHaveTextContent(t("role.viewOnly"));
    rerender(<RoleBadge userRole="admin" />);
    expect(screen.getByTestId("role-badge")).toHaveTextContent("Admin");
    rerender(<RoleBadge userRole={undefined} />);
    expect(screen.getByTestId("role-badge")).toHaveTextContent(t("role.signedOut"));
  });

  it("names the account only for an OpenStreetMap sign-in", () => {
    const { rerender } = render(<RoleBadge userRole="reviewer" name="Mae" viaOsm />);
    expect(screen.getByTestId("reviewing-as")).toHaveTextContent("Reviewing as Mae");
    rerender(<RoleBadge userRole="reviewer" name="Mae" />);
    expect(screen.queryByTestId("reviewing-as")).toBeNull();
  });
});

describe("LaneChip", () => {
  it("gives every lane a glyph and a text label", () => {
    for (const meta of LANES) {
      const { unmount } = render(<LaneChip lane={meta.lane} count={3} />);
      const chip = document.querySelector(`[data-lane="${meta.lane}"]`);
      expect(chip).toHaveTextContent(t(meta.label));
      expect(chip).toHaveTextContent(meta.glyph);
      expect(chip).toHaveTextContent("3");
      unmount();
    }
  });
});
