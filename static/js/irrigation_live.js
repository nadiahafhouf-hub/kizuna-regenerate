/* Page Irrigation — planning enregistré en base, automate simulé côté serveur.
   - graphique solaire / pompe du jour choisi (cartes des 7 jours) ;
   - état en direct (vannes, réservoir, quota, eau économisée) rafraîchi toutes les 3 s ;
   - « Simuler la journée suivante » : POST, puis petite animation des vannes ouvertes. */

document.addEventListener("alpine:init", () => {
  const T = UI.irrigation;
  let chart = null;   // hors de l'état Alpine (Chart.js n'aime pas les proxys réactifs)

  Alpine.data("irrigationLive", (cfg) => ({
    cfg,
    selected: 0,
    busy: false,
    msg: "",
    etat: JSON.parse((document.getElementById("etat-initial") || {}).textContent || "null") ||
          { vannes: [], reservoir: { niveau_l: 0, capacite_l: 1, pct: 0 }, quota: { pompe_l: 0, quota_l: 1, pct: 0 },
            economie: { economise_m3: 0, kwh: 0 }, horloge: "", semaine_finie: false },

    init() {
      this.$nextTick(() => this.drawChart());
      if (cfg.statut) setInterval(() => this.refresh(), 3000);
    },

    select(i) {
      this.selected = i;
      if (!chart) return;
      chart.data.datasets[0].data = cfg.days[i].hourly.solar;
      chart.data.datasets[1].data = cfg.days[i].hourly.pump;
      chart.update();
    },

    drawChart() {
      const el = document.getElementById("energy-chart");
      if (!el || !window.Chart) return;
      const ctx = el.getContext("2d");
      const grad = ctx.createLinearGradient(0, 0, 0, 260);
      grad.addColorStop(0, "rgba(232,169,22,0.45)");
      grad.addColorStop(1, "rgba(232,169,22,0.02)");
      Chart.defaults.font.family = "'DM Sans', system-ui, sans-serif";
      Chart.defaults.color = "#55684A";
      const d = cfg.days[this.selected];
      chart = new Chart(ctx, {
        type: "line",
        data: {
          labels: Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}h`),
          datasets: [
            { label: T.chart_solar, data: d.hourly.solar, borderColor: "#E8A916", backgroundColor: grad,
              fill: true, tension: 0.4, borderWidth: 2.5, pointRadius: 0, pointHoverRadius: 4 },
            { label: T.chart_pump, data: d.hourly.pump, borderColor: "#1F6FA8", backgroundColor: "rgba(31,111,168,0.12)",
              fill: true, stepped: true, borderWidth: 2.5, pointRadius: 0, pointHoverRadius: 4 },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 12 } },
            y: { beginAtZero: true, grid: { color: "#E7EFDD" }, title: { display: true, text: "kW" } },
          },
          plugins: {
            legend: { display: false },
            tooltip: { backgroundColor: "#172812", padding: 10, cornerRadius: 10,
                       callbacks: { label: (c) => ` ${c.dataset.label}: ${c.parsed.y.toFixed(2)}` } },
          },
        },
      });
    },

    async refresh() {
      if (this.busy) return;
      try { this.etat = await (await fetch(cfg.etatUrl)).json(); } catch (e) { /* serveur coupé : on réessaie */ }
    },

    async simulate() {
      this.busy = true;
      this.msg = "";
      try {
        const r = await fetch(cfg.simUrl, { method: "POST", headers: { "X-CSRFToken": csrfToken() } });
        const j = await r.json();
        if (!j.ok) { this.msg = T.need_auto; this.busy = false; return; }
        // animation : chaque vanne arrosée s'ouvre puis se referme
        const zones = [...new Set(j.traites.filter((t) => t.type === "ARROSAGE" && t.statut === "FAIT").map((t) => t.zone_id))];
        for (const z of zones) {
          this.etat = { ...j.etat, vannes: j.etat.vannes.map((v) => (v.zone_id === z ? { ...v, ouverte: true } : v)) };
          await new Promise((res) => setTimeout(res, 700));
        }
        this.etat = j.etat;
        this.msg = cfg.statut === "MANUEL" ? T.manual_clock : `${j.traites.length} ${T.processed}`;
        if (typeof toast === "function") toast(this.msg);
        // recharger pour mettre à jour les cartes jour et la liste des événements
        setTimeout(() => location.reload(), 900);
      } catch (e) {
        this.busy = false;
      }
    },
  }));
});
