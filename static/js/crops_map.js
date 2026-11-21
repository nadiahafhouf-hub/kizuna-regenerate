/* Bloc 2 — carte satellite du plan recommandé (terre nue).
   Données : advisor.services.geo.geojson_plan (cases, plantes, goutte-à-goutte, vannes, équipements).
   Utilise satelliteMap() / ZONE_HEX de map.js. */

function cropsPlanMap(el, G, T) {
  const map = satelliteMap(el, { scrollWheelZoom: false, zoomSnap: 0.5 });
  const kind = (k) => G.features.filter((f) => f.properties.kind === k);
  const geo = (feats, opts) => L.geoJSON({ type: "FeatureCollection", features: feats }, opts);
  const hex = (c) => ZONE_HEX[c] || "#6B6F5E";

  const zones = geo(kind("case"), {
    style: (f) => ({ color: hex(f.properties.couleur), weight: 2, fillColor: hex(f.properties.couleur), fillOpacity: 0.25 }),
    onEachFeature: (f, l) => {
      const p = f.properties;
      l.bindTooltip(`<b>${p.id}</b> · ${T.zone} ${p.zone_id || "—"}<br>EC ${p.CE_dS_m} dS/m<br>` +
        `${p.culture || "—"}${p.alimentaire === false ? ` · <b>${T.non_food}</b>` : ""}`, { sticky: true });
    },
  });
  const drip = geo(kind("goutte"), { style: { color: "#4DA3FF", weight: 1, opacity: 0.9 } });
  const drain = geo(kind("drainage"), { style: { color: "#6B3E1F", weight: 3, dashArray: "6 4" } });
  const plants = geo(kind("plante"), {
    pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 3.5, color: "#fff", weight: 1, fillColor: f.properties.hex, fillOpacity: 1 })
      .bindTooltip(f.properties.culture + (f.properties.alimentaire ? "" : ` (${T.non_food})`)),
  });
  const badge = (html, border) => L.divIcon({ className: "", iconSize: null,
    html: `<span style="background:#fff;border:2px solid ${border};border-radius:8px;padding:1px 6px;font:600 11px 'DM Sans',sans-serif;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,.3)">${html}</span>` });
  const equip = L.layerGroup([
    geo(kind("conduite"), { style: { color: "#1F6FA8", weight: 4 } }),
    geo(kind("vanne"), { pointToLayer: (f, ll) => L.marker(ll, { icon: L.divIcon({ className: "", iconSize: [14, 14],
        html: `<div style="width:14px;height:14px;background:#1E2316;border:3px solid ${f.properties.hex};border-radius:3px"></div>` }) })
      .bindTooltip(`${T.valve} V-${f.properties.zone_id} · ${f.properties.besoin_litres_jour} L/${T.day}`) }),
    geo([...kind("reservoir"), ...kind("pompe"), ...kind("panneaux")], { pointToLayer: (f, ll) =>
      L.marker(ll, { icon: badge(T.equipment[f.properties.kind] || f.properties.nom, "#1F6FA8") }) }),
  ]);
  const labels = geo(kind("etiquette"), { pointToLayer: (f, ll) => {
    const p = f.properties;
    return L.marker(ll, { interactive: false, icon: badge(
      `${p.zone_id} · ${p.culture}<br><span style="font-weight:400">${p.besoin_litres_jour} L/${T.day}${p.alimentaire ? "" : " · " + T.non_food}</span>`,
      hex(p.couleur)) });
  } });

  [zones, drip, drain, plants, equip, labels].forEach((l) => l.addTo(map));
  L.control.layers(null, { [T.layers.zones]: zones, [T.layers.plants]: plants, [T.layers.drip]: drip,
    [T.layers.drain]: drain, [T.layers.equipment]: equip, [T.layers.labels]: labels }, { collapsed: true }).addTo(map);
  L.control.scale({ imperial: false }).addTo(map);
  const fit = () => { map.invalidateSize(); map.fitBounds(G.bounds, { padding: [12, 12] }); };
  fit();
  // la carte peut être créée cachée (onglet ou mode « terre nue » pas encore choisi) : on recale dès qu'elle apparaît
  let w = el.clientWidth;
  new ResizeObserver(() => { if (el.clientWidth && el.clientWidth !== w) { w = el.clientWidth; fit(); } }).observe(el);
  return map;
}

window.cropsPlanMap = cropsPlanMap;
