/* Bloc 3 — page Irrigation : planning 7 jours, graphique solaire/pompe et simulation temps réel.
   Tout est simulé côté navigateur à partir du planning calculé par services/demo_data.py. */

document.addEventListener("alpine:init", () => {
  const T = UI.irrigation;
  const hhmm = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(Math.round(m) % 60).padStart(2, "0")}`;
  const toMin = (s) => { const [h, m] = s.split(":").map(Number); return h * 60 + m; };

  let chart = null; // hors de l'état Alpine (Chart.js n'aime pas les proxys réactifs)
  let timer = null;

  Alpine.data("irrigationPage", (cfg) => ({
    mode: cfg.approved ? "AUTO" : "PENDING",
    selected: 0,
    // état de la simulation
    t: 5 * 60 + 45,
    simDay: 0,
    speed: 10,
    valveOpen: false,
    valveZone: null,
    pumpOn: false,
    reservoir: cfg.system.reservoir_m3 * cfg.system.reservoir_start_pct / 100,
    moisture: 31,
    solarKw: 0,
    savedLive: 0,
    deliveredLive: 0,
    log: [],

    init() {
      this.$nextTick(() => { this.drawChart(); });
      if (this.mode === "AUTO") this.start(false);
    },

    get day() { return cfg.days[this.selected]; },
    get simDayData() { return cfg.days[this.simDay]; },
    get clock() { return hhmm(this.t); },
    get reservoirPct() { return Math.round(this.reservoir / cfg.system.reservoir_m3 * 100); },
    get capacity() { return cfg.system.reservoir_m3; },
    cfgKwp() { return cfg.system.solar_kwp; },

    /* ── Planning & graphique ── */
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
      chart = new Chart(ctx, {
        type: "line",
        data: {
          labels: Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}h`),
          datasets: [
            { label: T.chart_solar, data: this.day.hourly.solar, borderColor: "#E8A916", backgroundColor: grad,
              fill: true, tension: 0.4, borderWidth: 2.5, pointRadius: 0, pointHoverRadius: 4 },
            { label: T.chart_pump, data: this.day.hourly.pump, borderColor: "#1F6FA8", backgroundColor: "rgba(31,111,168,0.12)",
              fill: true, stepped: true, borderWidth: 2.5, pointRadius: 0, pointHoverRadius: 4 },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          animation: { duration: 900, easing: "easeOutQuart" },
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

    /* ── Validation du plan ── */
    async approve() {
      try {
        await fetch(cfg.approveUrl, { method: "POST", headers: { "X-CSRFToken": csrfToken() } });
      } catch (e) { /* démo : on bascule quand même */ }
      this.$dispatch("close-modal");
      this.mode = "AUTO";
      toast(T.approved_toast);
      this.start(true);
      this.$nextTick(() => document.getElementById("live-panel")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    },

    /* ── Simulation ── */
    addLog(text, kind = "info", at = this.t) {
      this.log.unshift({ id: Date.now() + Math.random(), time: hhmm(at), text, kind });
      if (this.log.length > 40) this.log.pop();
    },

    start(fresh) {
      if (fresh) { this.t = 5 * 60 + 45; this.simDay = 0; }
      this.addLog(T.log.auto_on, "auto");
      clearInterval(timer);
      timer = setInterval(() => this.tick(), 1000);
      this.tick(0);
    },

    setSpeed(s) { this.speed = s; },

    tick(dt = this.speed) {
      const prev = this.t;
      let now = prev + dt;
      const sys = cfg.system;
      const d = this.simDayData;
      const inWin = (m, a, b) => m > a && m <= b;

      // Irrigation automatique : ouverture puis fermeture de chaque créneau
      if (this.mode === "AUTO") {
        d.slots.forEach((s) => {
          const a = toMin(s.start), b = a + s.minutes;
          if (inWin(a, prev, now)) {
            this.valveOpen = true; this.valveZone = s.zone;
            this.addLog(`${T.log.valve_open} — ${s.volume_m3.toFixed(2)} m³ — ${T.log.zone} ${s.zone}`, "water", a);
            this.reservoir = Math.max(0, this.reservoir - s.volume_m3);
            this.deliveredLive += s.volume_m3;
            const factor = d.irrigation_m3 > 0 ? d.flood_m3 / d.irrigation_m3 - 1 : 0;
            this.savedLive += s.volume_m3 * factor;
            this.moisture = Math.min(48, this.moisture + 4);
          }
          if (inWin(b, prev, now)) {
            this.valveOpen = false; this.valveZone = null;
            this.addLog(`${T.log.valve_closed} — ${T.log.zone} ${s.zone}`, "info", b);
          }
        });
      }

      // Pompage solaire vers le réservoir à midi
      const pa = toMin(d.pump.start), pb = toMin(d.pump.end);
      if (d.pump.hours > 0) {
        if (inWin(pa, prev, now)) {
          this.pumpOn = true;
          const kw = d.hourly.solar[Math.floor(pa / 60)] || 0;
          this.addLog(`${T.log.pump_on} — ${kw.toFixed(1)} kW ${T.log.available}`, "sun", pa);
        }
        if (this.pumpOn) {
          const end = Math.min(now, pb);
          const mins = Math.max(0, end - Math.max(prev, pa));
          this.reservoir = Math.min(sys.reservoir_m3, this.reservoir + sys.pump_flow_m3h * mins / 60);
        }
        if (inWin(pb, prev, now)) {
          this.pumpOn = false;
          this.addLog(T.log.pump_off, "sun", pb);
        }
      }

      // Vanne ouverte à la main
      if (this.mode === "MANUAL" && this.valveOpen && dt > 0) {
        const v = sys.drip_flow_m3h * dt / 60;
        this.reservoir = Math.max(0, this.reservoir - v);
        this.deliveredLive += v;
        this.moisture = Math.min(55, this.moisture + 0.8 * dt / 5);
        if (this.reservoir <= 0) {
          this.valveOpen = false; this.valveZone = null;
          this.addLog(T.log.empty, "warn", now);
        }
      }

      // Évaporation pendant la journée
      const h = (now / 60) % 24;
      if (h > 8 && h < 18) this.moisture = Math.max(18, this.moisture - 0.12 * dt / 5);

      // Production solaire instantanée
      const sol = d.hourly.solar;
      const hi = Math.floor(h), frac = h - hi;
      const base = (sol[hi] || 0) * (1 - frac) + (sol[(hi + 1) % 24] || 0) * frac;
      this.solarKw = base > 0 ? base * (0.94 + Math.random() * 0.06) : 0;

      // Passage à minuit
      if (now >= 1440) { now -= 1440; this.simDay = (this.simDay + 1) % cfg.days.length; }
      this.t = now;
    },

    /* ── Commande manuelle ── */
    override() {
      this.mode = "MANUAL";
      this.addLog(T.log.manual, "warn");
    },
    toggleValve() {
      this.valveOpen = !this.valveOpen;
      this.valveZone = this.valveOpen ? "ALL" : null;
      this.addLog(`${T.log.manual} — ${this.valveOpen ? T.log.valve_open : T.log.valve_closed}`, "warn");
    },
    resume() {
      this.mode = "AUTO";
      this.valveOpen = false; this.valveZone = null;
      this.addLog(T.log.resume, "auto");
    },
  }));
});
