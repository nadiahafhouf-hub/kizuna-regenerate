/* Bloc 3 · réseau goutte-à-goutte : outil de clic sur l'image (aperçu satellite ou photo envoyée).
   Étapes : 4 coins (photo seulement), source d'eau, plantes (facultatif).
   Les points sont écrits dans les champs cachés coins_px / source_px / plantes_px, en pixels de
   l'image ANALYSÉE (aperçu agrandi : division par "scale"). */
(function () {
  const cfg = JSON.parse(document.getElementById("net-config").textContent);
  const S = UI.network;
  const form = document.getElementById("net-form");
  const cv = document.getElementById("net-canvas"), ctx = cv.getContext("2d");
  const etat = document.getElementById("net-help"), info = document.getElementById("net-preview-info");
  const btnPreview = document.getElementById("net-preview");
  const champ = (k) => form.querySelector(`input[name=${k}_px]`);
  const zoom = form.querySelector("input[name=satellite_zoom]");
  const photo = form.querySelector("input[name=photo]");
  const pts = { coins: [], source: [], plantes: [] }, max = { coins: 4, source: 1, plantes: 5000 };
  const noms = ["NW", "NE", "SE", "SW"];
  let mode = "coins", img = new Image(), pret = false, hist = [], coinsFixes = false, echelle = 1;

  const source = () => (form.querySelector("input[name=source_image]:checked") || {}).value || "satellite";
  const enPx = (l) => l.map((p) => [+(p[0] / echelle).toFixed(2), +(p[1] / echelle).toFixed(2)]);

  function maj() {
    for (const k of ["coins", "source", "plantes"]) {
      const c = champ(k);
      if (k === "coins" && (coinsFixes || pts.coins.length < 4)) c.value = "";
      else c.value = pts[k].length ? JSON.stringify(enPx(pts[k])) : "";
      const n = document.getElementById("net-n-" + k);
      if (n) n.textContent = pts[k].length + (k === "plantes" ? "" : "/" + max[k]);
    }
    document.querySelectorAll("[data-net-mode]").forEach((b) => {
      const actif = b.dataset.netMode === mode;
      b.classList.toggle("bg-olive-700", actif); b.classList.toggle("text-white", actif);
      b.classList.toggle("bg-white", !actif);
    });
    // en mode satellite, les coins viennent du GPS : jamais à cliquer
    document.querySelector("[data-net-mode=coins]").classList.toggle("hidden", coinsFixes || source() === "satellite");
    etat.textContent = pret ? S["help_" + (mode === "coins" ? "corners" : mode === "source" ? "source" : "plants")]
                            : (source() === "satellite" ? S.help_empty : S.photo_hint);
    dessin();
  }

  function dessin() {
    if (!pret) return;
    ctx.drawImage(img, 0, 0);
    const lw = Math.max(2, cv.width / 350), r = lw * 3;
    ctx.lineWidth = lw; ctx.font = "bold " + Math.max(14, cv.width / 45) + "px DM Sans, sans-serif";
    const c = pts.coins; ctx.strokeStyle = "#ff1744"; ctx.fillStyle = "#ff1744";
    if (c.length > 1) { ctx.beginPath(); ctx.moveTo(...c[0]); c.slice(1).forEach((p) => ctx.lineTo(...p)); if (c.length === 4) ctx.closePath(); ctx.stroke(); }
    c.forEach((p, i) => { ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 7); ctx.fill(); ctx.strokeStyle = "#fff"; ctx.strokeText(noms[i], p[0] + r, p[1] - r); ctx.fillText(noms[i], p[0] + r, p[1] - r); ctx.strokeStyle = "#ff1744"; });
    pts.source.forEach((p) => { ctx.fillStyle = "#1F6FA8"; ctx.beginPath(); ctx.moveTo(p[0], p[1] - 2 * r); ctx.lineTo(p[0] - 1.7 * r, p[1] + r); ctx.lineTo(p[0] + 1.7 * r, p[1] + r); ctx.closePath(); ctx.fill(); });
    pts.plantes.forEach((p) => { ctx.strokeStyle = "#00e676"; ctx.beginPath(); ctx.arc(p[0], p[1], r * 1.3, 0, 7); ctx.stroke(); });
  }

  function choisir(m) { mode = m; maj(); }

  function vider() {
    pret = false; coinsFixes = false; echelle = 1; hist = [];
    for (const k in pts) pts[k] = [];
    cv.classList.add("hidden"); zoom.value = ""; info.innerHTML = "";
    choisir(source() === "satellite" ? "source" : "coins");
  }

  function charger(src, opts) {
    opts = opts || {};
    img = new Image();
    img.onload = () => {
      cv.classList.remove("hidden"); cv.width = img.naturalWidth; cv.height = img.naturalHeight;
      pret = true; hist = []; for (const k in pts) pts[k] = [];
      echelle = opts.scale || 1; coinsFixes = !!opts.corners;
      if (opts.corners) pts.coins = opts.corners.map((p) => [p[0], p[1]]);
      choisir(coinsFixes ? "source" : "coins");
    };
    img.src = src;
  }

  document.querySelectorAll("[data-net-mode]").forEach((b) => (b.onclick = () => choisir(b.dataset.netMode)));
  document.getElementById("net-undo").onclick = () => { const k = hist.pop(); if (k) pts[k].pop(); maj(); };

  cv.addEventListener("pointerup", (e) => {
    if (!pret || (mode === "coins" && coinsFixes)) return;
    if (pts[mode].length >= max[mode]) { if (mode === "source") pts.source = []; else return; }
    const r = cv.getBoundingClientRect();
    pts[mode].push([(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]);
    hist.push(mode);
    if (mode === "coins" && pts.coins.length === 4) return choisir("source");
    maj();
  });

  // Choix de la source d'image
  form.querySelectorAll("input[name=source_image]").forEach((r) => r.addEventListener("change", () => {
    const sat = source() === "satellite";
    document.getElementById("net-block-satellite").classList.toggle("hidden", !sat);
    document.getElementById("net-block-photo").classList.toggle("hidden", sat);
    if (photo) photo.value = "";
    vider();
  }));

  if (photo) photo.addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (f) charger(URL.createObjectURL(f));
  });

  // Aperçu satellite
  btnPreview.addEventListener("click", async () => {
    const fd = new FormData();
    fd.append("csrfmiddlewaretoken", form.querySelector("[name=csrfmiddlewaretoken]").value);
    btnPreview.disabled = true; info.className = "mt-2 text-sm text-muted"; info.textContent = S.previewing;
    try {
      const r = await fetch(cfg.previewUrl, { method: "POST", body: fd });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "HTTP " + r.status);
      zoom.value = d.zoom;
      charger(d.image, { corners: d.corners, scale: d.scale });
      info.textContent = d.legend;
      d.warnings.forEach((w) => { const p = document.createElement("p"); p.className = "mt-1 rounded-lg bg-sun-50 px-2 py-1 text-xs text-sun-700"; p.textContent = w; info.appendChild(p); });
    } catch (err) {
      info.className = "mt-2 rounded-lg bg-zred-bg px-3 py-2 text-sm text-zred"; info.textContent = err.message;
    } finally { btnPreview.disabled = false; }
  });

  form.addEventListener("submit", () => {
    const b = document.getElementById("net-submit");
    b.disabled = true; b.querySelector("span").textContent = S.computing;
  });

  vider();

  // Petite carte : réseau en GPS sur l'imagerie Esri
  const el = document.getElementById("net-map");
  if (el && cfg.geojsonUrl && window.L) {
    const map = L.map(el, { scrollWheelZoom: false });
    L.tileLayer(cfg.tiles, { maxZoom: 21, maxNativeZoom: cfg.zoom || 18, attribution: cfg.attribution }).addTo(map);
    const style = { parcelle: { color: "#fff", weight: 3, fill: false }, zone: { weight: 1, fillOpacity: 0.15 },
      rampe: { color: "#4FA3D9", weight: 1.5 }, porte_rampe: { color: "#F5CB5C", weight: 3 },
      conduite_principale: { color: "#1E2316", weight: 5 } };
    const zc = { ROUGE: "#B83227", ORANGE: "#B85C0E", VERT: "#23774A", JAUNE: "#E8A916" };
    fetch(cfg.geojsonUrl).then((r) => r.json()).then((g) => {
      const layer = L.geoJSON(g, {
        style: (f) => { const c = f.properties.couche, s = Object.assign({}, style[c] || { color: "#fff", weight: 1 });
          if (c === "zone") s.color = zc[String(f.properties.couleur || "").toUpperCase()] || "#6B6F5E"; return s; },
        pointToLayer: (f, ll) => { const o = { plante_existante: ["#3cdc3c", 4], plante_a_planter: ["#ff8c00", 4],
            vanne: ["#000", 5], source: ["#1F6FA8", 7] }[f.properties.couche] || ["#fff", 3];
          return L.circleMarker(ll, { radius: o[1], color: "#000", weight: 1, fillColor: o[0], fillOpacity: 0.95 }); },
        onEachFeature: (f, l) => l.bindTooltip(f.properties.couche.replace(/_/g, " ") + (f.properties.zone ? " · " + f.properties.zone : "")),
      }).addTo(map);
      map.fitBounds(layer.getBounds(), { padding: [20, 20] });
    });
  }
})();
