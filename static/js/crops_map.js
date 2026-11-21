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

/* Mode « Already planted » : même fond satellite Esri, zones de la parcelle, et le CHEMIN D'IRRIGATION
   calculé par le bloc 3 (GeoJSON de irrigation:network_geojson). Rechargé après chaque calcul du réseau. */
/* Terre déjà plantée — vue du CHAMP entier (advisor.services.champ) : arbres détectés sur l'image,
   rectangle du champ orienté sur l'axe des sillons, chemin d'irrigation (conduite principale,
   rampes par rang d'arbres, vannes par secteur, source). Le repère (croix) se déplace : clic ou glisser. */
function plantedFieldMap(el, G, T, onMove) {
  const map = L.map(el, { zoomControl: true, scrollWheelZoom: false, dragging: !L.Browser.mobile, zoomSnap: 0.25 });
  L.tileLayer(ESRI_WORLD_IMAGERY, {
    maxZoom: 21, maxNativeZoom: 18,
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
  }).addTo(map);
  const hex = (c) => ZONE_HEX[c] || "#6B6F5E";
  const zones = L.geoJSON({ type: "FeatureCollection", features: G.features.filter((f) => f.properties.kind === "case") }, {
    style: (f) => ({ color: hex(f.properties.couleur), weight: 1.5, fillColor: hex(f.properties.couleur), fillOpacity: 0.18 }),
    onEachFeature: (f, l) => l.bindTooltip(`<b>${T.zone} ${f.properties.zone_id || "—"}</b> · ${f.properties.id}`, { sticky: true }),
  });
  const ctl = L.control.layers(null, { [T.layers.zones]: zones }, { collapsed: true }).addTo(map);
  L.control.scale({ imperial: false }).addTo(map);

  const STYLE = {
    champ: { color: "#FFFFFF", weight: 2, dashArray: "8 5", fillColor: "#FFFFFF", fillOpacity: 0.05 },
    conduite_principale: { color: "#0B3D91", weight: 6 },
    rampe: { color: "#7FD3FF", weight: 2.5 },
  };
  const POINT = {
    plante_existante: (ll, p) => L.circle(ll, { radius: Math.max(1, p.diam_couronne_m / 2), color: "#0E3B12", weight: 1,
      fillColor: "#3FBF5F", fillOpacity: 0.6 })
      .bindTooltip(`${T.layers.existing} · Ø ${p.diam_couronne_m} m<br>${p.goutteurs} ${T.drippers} · ${p.l_jour} L/${T.day}`),
    vanne: (ll, p) => L.marker(ll, { icon: L.divIcon({ className: "", iconSize: [18, 18], iconAnchor: [9, 9],
      html: `<div style="width:18px;height:18px;display:grid;place-items:center;background:#1E2316;color:#fff;font:700 10px system-ui;border:2px solid #7FD3FF;border-radius:4px;box-shadow:0 0 0 1.5px #fff">${p.secteur}</div>` }) })
      .bindTooltip(`${T.layers.valve} ${p.secteur} · ${p.arbres} ${T.trees} · ${p.debit_m3_h} m³/h · ${p.heures} h/${T.day}`),
    source: (ll) => L.marker(ll, { icon: L.divIcon({ className: "", iconSize: [28, 28], iconAnchor: [14, 14],
      html: '<div style="width:28px;height:28px;display:grid;place-items:center;background:#fff;border:2px solid #0B3D91;border-radius:999px;font-size:15px;box-shadow:0 1px 3px rgba(0,0,0,.35)">💧</div>' }) })
      .bindTooltip(T.layers.source),
  };
  const NOMS = { champ: T.layers.field, conduite_principale: T.layers.main, rampe: T.layers.lateral,
                 vanne: T.layers.valve, source: T.layers.source, plante_existante: T.layers.existing };

  // repère du centre du champ : glisser, ou cliquer sur la carte
  const croix = L.marker([0, 0], { draggable: true, zIndexOffset: 1000, icon: L.divIcon({ className: "", iconSize: [30, 30], iconAnchor: [15, 15],
    html: '<div style="width:30px;height:30px;border:2px solid #FFD54A;border-radius:999px;background:rgba(255,213,74,.18);box-shadow:0 0 0 1.5px rgba(0,0,0,.5)"><div style="position:absolute;left:14px;top:4px;width:2px;height:22px;background:#FFD54A"></div><div style="position:absolute;top:14px;left:4px;height:2px;width:22px;background:#FFD54A"></div></div>' }) })
    .bindTooltip(T.move_hint);
  croix.on("dragend", () => onMove(croix.getLatLng()));
  map.on("click", (e) => { croix.setLatLng(e.latlng).addTo(map); onMove(e.latlng); });

  let couches = [];
  let cadre = G.bounds;
  const fit = (b) => { if (b) cadre = b; map.invalidateSize(); map.fitBounds(cadre, { padding: [16, 16], animate: false }); };

  function afficher(r) {
    couches.forEach((l) => { map.removeLayer(l); ctl.removeLayer(l); });
    couches = [];
    const feats = (r && r.geojson && r.geojson.features) || [];
    for (const couche of ["champ", "rampe", "conduite_principale", "plante_existante", "vanne", "source"]) {
      const fs = feats.filter((f) => f.properties.couche === couche);
      if (!fs.length) continue;
      const layer = L.geoJSON({ type: "FeatureCollection", features: fs }, {
        style: () => ({ ...STYLE[couche], opacity: 0.95, lineCap: "round" }),
        pointToLayer: (f, ll) => POINT[couche](ll, f.properties),
        onEachFeature: (f, l) => {
          if (couche === "rampe") l.bindTooltip(`${T.layers.lateral} · ${T.layers.valve} ${f.properties.secteur} · Ø 16 mm · ${f.properties.longueur_m} m · ${f.properties.arbres} ${T.trees}`, { sticky: true });
          if (couche === "conduite_principale") l.bindTooltip(`${T.layers.main} · Ø ${f.properties.diametre_mm} mm · ${f.properties.longueur_m} m`, { sticky: true });
        },
      }).addTo(map);
      ctl.addOverlay(layer, NOMS[couche]);
      couches.push(layer);
    }
    if (r && r.centre) croix.setLatLng([r.centre.lat, r.centre.lon]).addTo(map);
    const champ = couches[0];
    if (champ) fit(champ.getBounds().pad(0.12));
  }

  let w = el.clientWidth;
  // créée cachée (mode « Bare land » au chargement) : on recadre dès qu'elle apparaît
  new ResizeObserver(() => { if (el.clientWidth && el.clientWidth !== w) { w = el.clientWidth; fit(); } }).observe(el);
  fit();
  return { map, afficher };
}

window.plantedFieldMap = plantedFieldMap;
