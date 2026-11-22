/* Bloc 1 — carte du diagnostic : grille colorée, capteurs, clic sur une case → panneau (HTMX). */
(function () {
  const data = JSON.parse(document.getElementById("map-data").textContent);
  const map = satelliteMap("diag-map", { maxZoom: 21 });
  let selected = null;
  const cellLayers = {};

  let showConfidence = false;
  let layerMode = "zones";
  // Calques satellite (Sentinel-2) : échelles de couleur par indice
  const SCALES = {
    ndvi: { min: -0.05, max: 0.6, colors: ["#B98B5E", "#EDE3B4", "#2F7D32"], legend: UI.satellite.legend_ndvi },
    ndmi: { min: -0.25, max: 0.35, colors: ["#C0712B", "#F1E7C8", "#1F6FA8"], legend: UI.satellite.legend_ndmi },
    si: { min: 0.08, max: 0.3, colors: ["#E7EFDD", "#E3A6BE", "#8E2A63"], legend: UI.satellite.legend_si },
  };
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  function ramp(colors, t) {
    t = Math.max(0, Math.min(1, t));
    const seg = t * (colors.length - 1), i = Math.min(colors.length - 2, Math.floor(seg)), u = seg - i;
    const a = hex(colors[i]), b = hex(colors[i + 1]);
    return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * u)).join(",")})`;
  }
  function satStyle(f) {
    const s = f.properties.satellite, sc = SCALES[layerMode];
    const v = s && s.valide ? s[layerMode] : null;
    // l'indice de sel n'a de sens que sur sol nu (NDVI < 0.2)
    if (v === null || v === undefined || (layerMode === "si" && s.ndvi >= 0.2)) {
      return { color: "#FFFFFF", weight: 1, dashArray: "3 3", fillColor: "#9CA3AF", fillOpacity: 0.25 };
    }
    return { color: "#FFFFFF", weight: 1.5, fillColor: ramp(sc.colors, (v - sc.min) / (sc.max - sc.min)), fillOpacity: 0.8 };
  }
  // Calque « confiance » : les cases interpolées loin des points deviennent pâles et en pointillés
  const baseStyle = (f) => {
    if (layerMode !== "zones") return satStyle(f);
    const conf = f.properties.confiance;
    if (showConfidence && conf !== undefined) {
      return { color: "#FFFFFF", weight: f.properties.source === "capteur" ? 2.5 : 1.5,
               dashArray: f.properties.source === "capteur" ? null : "4 4",
               fillColor: ZONE_HEX[f.properties.couleur], fillOpacity: 0.12 + 0.68 * conf };
    }
    return { color: "#FFFFFF", weight: 1.5, fillColor: ZONE_HEX[f.properties.couleur], fillOpacity: 0.55 };
  };

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
      const conf = p.niveau_confiance ? `<br>${UI.diagnostic.confidence}: ${UI.diagnostic.confidence_levels[p.niveau_confiance]} (${Math.round(p.confiance * 100)}%)` : "";
      const s = p.satellite;
      const sat = s && s.valide ? `<br><span style="color:#55684A">NDVI ${s.ndvi} · NDMI ${s.ndmi} · SI ${s.si}</span>` : "";
      layer.bindTooltip(`${ZONE_ICON_SVG[p.couleur]} <b>${z.label}</b> · ${UI.diagnostic.row} ${p.ligne}, ${UI.diagnostic.col} ${p.col}${p.zone ? " · " + p.zone : ""}${conf}${sat}`,
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

  const toggle = document.getElementById("conf-toggle");
  if (toggle) toggle.addEventListener("change", () => {
    showConfidence = toggle.checked;
    grid.eachLayer((l) => { if (l !== selected) grid.resetStyle(l); });
  });
  map.fitBounds(data.bounds, { padding: [30, 30] });

  let chatZones;
  document.addEventListener("chat-focus", ({ detail }) => {
    chatZones?.remove();
    chatZones = null;
    map.invalidateSize({ pan: false });
    if (detail !== "red-zone") return;
    document.querySelector('.layer-btn[data-layer="zones"]')?.click();
    chatZones = L.geoJSON(data.geojson, {
      filter: (feature) => feature.properties.couleur === "ROUGE",
      interactive: false,
      style: { color: "#7d251d", weight: 4, fillColor: "#df5745", fillOpacity: .32 },
    }).addTo(map);
    const bounds = chatZones.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 20, animate: false });
  });

  // Sélecteur de calque satellite
  const legend = document.getElementById("sat-legend");
  document.querySelectorAll(".layer-btn").forEach((btn) => btn.addEventListener("click", () => {
    layerMode = btn.dataset.layer;
    document.querySelectorAll(".layer-btn").forEach((b) => {
      const on = b === btn;
      b.classList.toggle("bg-olive-700", on); b.classList.toggle("text-white", on);
      b.classList.toggle("text-muted", !on);
    });
    grid.eachLayer((l) => grid.resetStyle(l));
    selected = null;
    if (legend) {
      const sc = SCALES[layerMode];
      legend.classList.toggle("hidden", !sc);
      if (sc) {
        document.getElementById("sat-legend-bar").style.background = `linear-gradient(90deg, ${sc.colors.join(",")})`;
        document.getElementById("sat-legend-lo").textContent = sc.legend[0];
        document.getElementById("sat-legend-hi").textContent = sc.legend[1];
        document.getElementById("sat-legend-note").classList.toggle("hidden", layerMode !== "si");
      }
    }
  }));

  // Points de contrôle proposés par le satellite (cases non mesurées anormales)
  (data.controles || []).forEach((c) => {
    const l = cellLayers[`${c.ligne}-${c.col}`];
    if (!l) return;
    L.circle(l.getBounds().getCenter(), { radius: 4, color: "#E8A916", weight: 3, dashArray: "4 3", fill: false })
      .addTo(map).bindTooltip(`${UI.satellite.controls_title} · NDVI ${c.ndvi} (${c.ndvi_zone})`);
  });

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
    L.circle([s.lat, s.lon], { radius: s.radius_km * 1000, color: "#FFFFFF", weight: 1.5, dashArray: "5 5", fillColor: "#172812", fillOpacity: 0.2 })
      .addTo(ctx).bindTooltip(`<b>${s.name}</b><br>${s.pollutants.join(", ")}`);
    b.extend(L.latLng(s.lat, s.lon).toBounds(s.radius_km * 2000));
  });
  L.circleMarker(data.center, { radius: 7, color: "#fff", weight: 3, fillColor: "#E8A916", fillOpacity: 1 }).addTo(ctx);
  ctx.fitBounds(b.pad(0.05));
})();
