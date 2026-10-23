import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OsmAttribution } from "./OsmAttribution";

describe("OsmAttribution", () => {
  it("is shown even when the server sent no attribution", () => {
    render(<OsmAttribution attribution={undefined} />);
    expect(screen.getByTestId("attribution")).toHaveTextContent("OpenStreetMap contributors");
    expect(screen.getByTestId("attribution")).toHaveTextContent("ODbL");
  });

  it("is shown when the server sent empty strings", () => {
    render(<OsmAttribution attribution={{ copyright: "", attribution: "", license: "" }} />);
    expect(screen.getByTestId("attribution")).toHaveTextContent("OpenStreetMap contributors");
  });

  it("uses the server's text when there is some", () => {
    render(
      <OsmAttribution attribution={{ copyright: "© OSM contributors", license: "ODbL 1.0" }} />,
    );
    expect(screen.getByTestId("attribution")).toHaveTextContent("© OSM contributors · ODbL 1.0");
  });
});
