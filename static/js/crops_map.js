/* Bloc 2 — carte satellite du plan recommandé (terre nue).
   Données : advisor.services.geo.geojson_plan (cases, plantes, goutte-à-goutte, vannes, équipements).
   Fond : L.tileLayer Esri World Imagery ; zoneLegend() / ZONE_HEX de map.js : mêmes couleurs que le site. */

// Fond satellite : API de tuiles Esri World Imagery (gratuite, sans clé, crédit obligatoire).
// À Gabès, l'imagerie existe jusqu'au zoom 18 : au-delà, Leaflet agrandit la tuile 18.
const ESRI_WORLD_IMAGERY = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

function cropsPlanMap(el, G, T) {
  const map = L.map(el, { zoomControl: true, scrollWheelZoom: false, dragging: !L.Browser.mobile, zoomSnap: 0.5 });
  L.tileLayer(ESRI_WORLD_IMAGERY, {
    maxZoom: 21, maxNativeZoom: 18,
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
  }).addTo(map);
  const kind = (k) => G.features.filter((f) => f.properties.kind === k);
  const geo = (feats, opts) => L.geoJSON({ type: "FeatureCollection", features: feats }, opts);
  const hex = (c) => ZONE_HEX[c] || "#6B6F5E";
  const court = (s, n = 24) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  // Zones : couleur franche + contour épais (lisible sur la photo)
  const zones = geo(kind("case"), {
    style: (f) => ({ color: hex(f.properties.couleur), weight: 3, fillColor: hex(f.properties.couleur), fillOpacity: 0.42 }),
    onEachFeature: (f, l) => {
      const p = f.properties;
      l.bindTooltip(`<b>${T.zone} ${p.zone_id || "—"}</b> · ${p.id}<br>EC ${p.CE_dS_m} dS/m<br>` +
        `${p.culture || "—"}${p.alimentaire === false ? ` · <b>${T.non_food}</b>` : ""}`, { sticky: true });
    },
  });
  const drip = geo(kind("goutte"), { style: { color: "#8EC9FF", weight: 1.2, opacity: 0.9 } });
  const drain = geo(kind("drainage"), { style: { color: "#3B2412", weight: 3, dashArray: "6 4" } });
  // Plantes : points blancs (gros pour les arbres) avec contour foncé -> visibles sur toutes les couleurs
  const plants = geo(kind("plante"), {
    pointToLayer: (f, ll) => L.circleMarker(ll, {
      radius: f.properties.arbre ? 6 : 3, color: "#1E2316", weight: 1, fillColor: "#FFFFFF", fillOpacity: 0.95,
    }).bindTooltip(f.properties.culture + (f.properties.alimentaire ? "" : ` (${T.non_food})`)),
  });
  // Équipements : petites icônes rondes, le nom au survol (ne cachent plus les vannes)
  const icone = (emoji, nom) => L.divIcon({ className: "", iconSize: [26, 26], iconAnchor: [13, 13],
    html: `<div title="${nom}" style="width:26px;height:26px;display:grid;place-items:center;background:#fff;border:2px solid #1F6FA8;border-radius:999px;font-size:14px;box-shadow:0 1px 3px rgba(0,0,0,.35)">${emoji}</div>` });
  const equip = L.layerGroup([
    geo(kind("conduite"), { style: { color: "#1F6FA8", weight: 4 } }),
    geo(kind("vanne"), { pointToLayer: (f, ll) => L.marker(ll, { icon: L.divIcon({ className: "", iconSize: [16, 16], iconAnchor: [8, 8],
        html: `<div style="width:16px;height:16px;background:#1E2316;border:3px solid ${hex(f.properties.couleur)};border-radius:4px;box-shadow:0 0 0 1.5px #fff"></div>` }) })
      .bindTooltip(`${T.valve} V-${f.properties.zone_id} · ${f.properties.besoin_litres_jour} L/${T.day}`) }),
    geo(kind("reservoir"), { pointToLayer: (f, ll) => L.marker(ll, { icon: icone("💧", T.equipment.reservoir) }).bindTooltip(T.equipment.reservoir) }),
    geo(kind("pompe"), { pointToLayer: (f, ll) => L.marker(ll, { icon: icone("⚙️", T.equipment.pompe) }).bindTooltip(T.equipment.pompe) }),
    geo(kind("panneaux"), { pointToLayer: (f, ll) => L.marker(ll, { icon: icone("☀️", T.equipment.panneaux) }).bindTooltip(T.equipment.panneaux) }),
  ]);
  // Étiquettes courtes : zone + eau, culture abrégée (nom complet au survol des cases)
  const labels = geo(kind("etiquette"), { pointToLayer: (f, ll) => {
    const p = f.properties;
    return L.marker(ll, { interactive: false, icon: L.divIcon({ className: "", iconSize: null,
      html: `<div style="transform:translate(-50%,-50%);background:#fff;border-left:5px solid ${hex(p.couleur)};border-radius:8px;padding:3px 8px;font:600 12px/1.25 'DM Sans',sans-serif;white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,.35);color:#1E2316">` +
            `${p.zone_id} · ${p.besoin_litres_jour} L/${T.day}<br><span style="font-weight:400;font-size:11px">${court(p.culture)}</span></div>` }) });
  } });

  [zones, drip, drain, plants, equip, labels].forEach((l) => l.addTo(map));
  L.control.layers(null, { [T.layers.zones]: zones, [T.layers.plants]: plants, [T.layers.drip]: drip,
    [T.layers.drain]: drain, [T.layers.equipment]: equip, [T.layers.labels]: labels }, { collapsed: true }).addTo(map);
  if (window.zoneLegend && window.UI && UI.zone) zoneLegend(map, UI.zone);
  L.control.scale({ imperial: false }).addTo(map);
  const fit = () => { map.invalidateSize(); map.fitBounds(G.bounds, { padding: [12, 12] }); };
  fit();
  // la carte peut être créée cachée (onglet ou mode « terre nue » pas encore choisi) : on recale dès qu'elle apparaît
  let w = el.clientWidth;
  new ResizeObserver(() => { if (el.clientWidth && el.clientWidth !== w) { w = el.clientWidth; fit(); } }).observe(el);
  return map;
}

window.cropsPlanMap = cropsPlanMap;
