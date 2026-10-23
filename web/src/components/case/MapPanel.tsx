import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { t } from "../../i18n";

/** OpenFreeMap vector style: no key, and nothing is requested until the reviewer asks for the map. */
export const MAP_STYLE_URL = "https://tiles.openfreemap.org/styles/bright";

type Bbox = readonly [number, number, number, number];

/**
 * The optional map. It is a separate chunk and is only mounted after the reviewer presses `m` or the
 * button, so no map request happens before that. The bounding box in words stays on the page; the map
 * only draws it. A failed load leaves a short note and everything else working.
 */
export default function MapPanel({ bbox }: { bbox: Bbox }) {
  const container = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const [west, south, east, north] = bbox;

  useEffect(() => {
    let map: MapLibreMap | null = null;
    let cancelled = false;
    void (async () => {
      try {
        const [maplibre] = await Promise.all([
          import("maplibre-gl"),
          import("maplibre-gl/dist/maplibre-gl.css"),
        ]);
        if (cancelled || !container.current) return;
        map = new maplibre.Map({
          container: container.current,
          style: MAP_STYLE_URL,
          bounds: [
            [west, south],
            [east, north],
          ],
          fitBoundsOptions: { padding: 24, animate: false },
          cooperativeGestures: true,
        });
        // A single missing tile has a source id and leaves the rest drawn; only a map that cannot
        // start (style, worker, WebGL) says it could not be loaded.
        map.on("error", (event) => {
          if (!(event as { sourceId?: string }).sourceId) setFailed(true);
        });
        map.on("load", () => {
          if (!map) return;
          map.addSource("changeset-bbox", {
            type: "geojson",
            data: {
              type: "Feature",
              properties: {},
              geometry: {
                type: "Polygon",
                coordinates: [
                  [
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                  ],
                ],
              },
            },
          });
          map.addLayer({
            id: "changeset-bbox-fill",
            type: "fill",
            source: "changeset-bbox",
            paint: { "fill-color": "#1d4ed8", "fill-opacity": 0.12 },
          });
          map.addLayer({
            id: "changeset-bbox-line",
            type: "line",
            source: "changeset-bbox",
            paint: { "line-color": "#1d4ed8", "line-width": 2 },
          });
        });
      } catch {
        // No WebGL, a blocked network or a missing chunk: the text above still says where this is.
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      map?.remove();
    };
  }, [west, south, east, north]);

  return (
    <div className="mt-3" data-testid="map-panel">
      <div
        ref={container}
        role="region"
        aria-label={t("case.map.label")}
        className="h-64 w-full rounded border border-border bg-surface"
      />
      {failed ? (
        <p role="status" className="mt-1 text-sm text-text-muted" data-testid="map-failed">
          {t("case.map.failed")}
        </p>
      ) : null}
      <p className="mt-1 text-xs text-text-muted" data-testid="map-attribution">
        {t("case.map.attribution")}
      </p>
    </div>
  );
}
