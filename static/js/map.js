/* Outils Leaflet partagés : fond satellite Esri, couleurs de zones, légende. */

const ZONE_HEX = { ROUGE: "#B83227", ORANGE: "#B85C0E", VERT: "#23774A" };
const ZONE_ICON_SVG = {
  ROUGE: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#B83227" stroke-width="2.4"><path d="M7.86 2h8.28L22 7.86v8.28L16.14 22H7.86L2 16.14V7.86L7.86 2z"/><path d="M12 8v4M12 16h.01"/></svg>',
  ORANGE: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#B85C0E" stroke-width="2.4"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4M12 17h.01"/></svg>',
  VERT: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#23774A" stroke-width="2.4"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>',
};

function satelliteMap(el, options = {}) {
  // Sur téléphone : pas de glisser à un doigt (sinon la carte « capture » le défilement de la page)
  const map = L.map(el, { zoomControl: true, scrollWheelZoom: false, dragging: !L.Browser.mobile, attributionControl: true, ...options });
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    // Imagerie disponible jusqu'au zoom 18 dans la région de Gabès (z19 = tuile « not available »)
    maxZoom: 21, maxNativeZoom: 18,
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
  }).addTo(map);
  return map;
}

function zoneLegend(map, labels, position = "bottomleft") {
  const ctl = L.control({ position });
  ctl.onAdd = () => {
    const div = L.DomUtil.create("div", "map-legend");
    div.innerHTML = ["ROUGE", "ORANGE", "VERT"].map((c) =>
      `<div style="display:flex;align-items:center;gap:6px">
         <span style="width:12px;height:12px;border-radius:3px;background:${ZONE_HEX[c]}"></span>
         ${ZONE_ICON_SVG[c]}<b>${labels[c].label}</b><span style="color:#55684A">· ${labels[c].long}</span>
       </div>`).join("");
    return div;
  };
  ctl.addTo(map);
  return ctl;
}

window.satelliteMap = satelliteMap;
window.zoneLegend = zoneLegend;
window.ZONE_HEX = ZONE_HEX;
window.ZONE_ICON_SVG = ZONE_ICON_SVG;
