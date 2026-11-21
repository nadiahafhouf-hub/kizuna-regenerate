/* Bloc 1 — carte du diagnostic : grille colorée, capteurs, clic sur une case → panneau (HTMX). */
(function () {
  const data = JSON.parse(document.getElementById("map-data").textContent);
  const map = satelliteMap("diag-map", { maxZoom: 21 });
  let selected = null;
  const cellLayers = {};

  const baseStyle = (f) => ({ color: "#FFFFFF", weight: 1.5, fillColor: ZONE_HEX[f.properties.couleur], fillOpacity: 0.55 });

  function select(layer) {
    if (selected) grid.resetStyle(selected);
    selected = layer;
    layer.setStyle({ color: "#F5CB5C", weight: 4, fillOpacity: 0.7 });
    layer.bringToFront();
    const p = layer.feature.properties;
    htmx.ajax("GET", data.caseUrl.replace("{l}", p.ligne).replace("{c}", p.col), { target: "#case-panel", swap: "innerHTML" });
    if (window.innerWidth < 1024) {
      document.getElementById("case-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  const grid = L.geoJSON(data.geojson, {
    style: baseStyle,
    onEachFeature: (f, layer) => {
      const p = f.properties;
      cellLayers[`${p.ligne}-${p.col}`] = layer;
      const z = UI.zone[p.couleur];
      layer.bindTooltip(`${ZONE_ICON_SVG[p.couleur]} <b>${z.label}</b> · ${UI.diagnostic.row} ${p.ligne}, ${UI.diagnostic.col} ${p.col}${p.zone ? " · " + p.zone : ""}`,
                        { sticky: true, direction: "top", opacity: 0.95 });
      layer.on({
        click: () => select(layer),
        mouseover: () => { if (layer !== selected) layer.setStyle({ fillOpacity: 0.75 }); },
        mouseout: () => { if (layer !== selected) grid.resetStyle(layer); },
      });
    },
  }).addTo(map);

  function addSensor(s) {
    const icon = L.divIcon({ className: "", html: `<div class="sensor-pin${s.new ? " new" : ""}"></div>`, iconSize: [18, 18], iconAnchor: [9, 9] });
    L.marker([s.lat, s.lon], { icon, zIndexOffset: 1000 }).addTo(map)
      .bindTooltip(`<b>${s.id}</b> · EC ${s.CE_dS_m} · Cd ${s.Cd_mg_kg}`, { direction: "top", offset: [0, -8] })
      .on("click", () => { const l = cellLayers[`${s.ligne}-${s.col}`]; if (l) select(l); });
  }
  data.sensors.forEach(addSensor);

  zoneLegend(map, UI.zone, "bottomleft");
  map.fitBounds(data.bounds, { padding: [30, 30] });

  // Fermeture du panneau
  document.addEventListener("case-clear", () => {
    if (selected) grid.resetStyle(selected);
    selected = null;
    document.getElementById("case-panel").innerHTML = document.getElementById("case-empty-tpl").innerHTML;
    icons();
  });

  // Nouveau relevé (en-tête HX-Trigger renvoyé par le serveur)
  document.body.addEventListener("reading-added", (e) => {
    const s = e.detail;
    addSensor({ ...s, new: true });
  });

  // Carte de contexte : sources de pollution configurables autour de la parcelle
  const ctx = satelliteMap("context-map", { zoomControl: false, attributionControl: false, dragging: true });
  const b = L.latLngBounds([data.center]);
  data.sources.forEach((s) => {
    L.circle([s.lat, s.lon], { radius: s.radius_km * 1000, color: "#FFFFFF", weight: 1.5, dashArray: "5 5", fillColor: "#1E2316", fillOpacity: 0.2 })
      .addTo(ctx).bindTooltip(`<b>${s.name}</b><br>${s.pollutants.join(", ")}`);
    b.extend(L.latLng(s.lat, s.lon).toBounds(s.radius_km * 2000));
  });
  L.circleMarker(data.center, { radius: 7, color: "#fff", weight: 3, fillColor: "#E8A916", fillOpacity: 1 }).addTo(ctx);
  ctx.fitBounds(b.pad(0.05));
})();
