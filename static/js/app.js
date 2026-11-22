/* Kizuna Regenerate — comportements communs (chargé sur toutes les pages, avant Alpine). */

const UI = JSON.parse(document.getElementById("ui-strings").textContent);

/* Icônes Lucide : à rappeler après tout contenu ajouté dynamiquement.
   Règle : ne jamais mettre de directive Alpine sur un <i data-lucide> (il est remplacé par un <svg>). */
window.icons = function () {
  if (window.lucide) lucide.createIcons({ attrs: { "stroke-width": 1.9 } });
};
document.addEventListener("DOMContentLoaded", icons);
document.body.addEventListener("htmx:afterSwap", icons);

function getCookie(name) {
  const m = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[2]) : "";
}
window.csrfToken = () => getCookie("csrftoken");

function fmt(n, decimals = 0) {
  return Number(n).toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
window.fmt = fmt;

/* Toasts : toast("Message", "success" | "error"), ou en-tête HTMX HX-Trigger: {"toast": {...}} */
window.toast = function (message, kind = "success") {
  if (window.Alpine) Alpine.store("toasts").push(message, kind);
};
document.body.addEventListener("toast", (e) => toast(e.detail.message, e.detail.kind));

document.addEventListener("alpine:init", () => {
  Alpine.store("toasts", {
    items: [],
    push(message, kind) {
      const t = { id: Date.now() + Math.random(), message, kind, visible: true };
      this.items.push(t);
      setTimeout(() => { t.visible = false; }, 3200);
      setTimeout(() => { this.items = this.items.filter((x) => x.id !== t.id); }, 3600);
    },
  });

  /* Chiffre qui compte jusqu'à sa valeur quand il devient visible */
  Alpine.data("countUp", (target, decimals = 0) => ({
    display: fmt(0, decimals),
    init() {
      const run = () => {
        const t0 = performance.now(), dur = 1200;
        const step = (now) => {
          const p = Math.min(1, (now - t0) / dur);
          const eased = 1 - Math.pow(1 - p, 3);
          this.display = fmt(target * eased, decimals);
          if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
        // filet de sécurité : onglet en arrière-plan = requestAnimationFrame en pause
        setTimeout(() => { this.display = fmt(target, decimals); }, dur + 400);
      };
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { this.display = fmt(target, decimals); return; }
      const io = new IntersectionObserver((entries) => {
        if (entries.some((e) => e.isIntersecting)) { run(); io.disconnect(); }
      });
      io.observe(this.$el);
    },
  }));

  /* Jauge circulaire qui se remplit */
  Alpine.data("gauge", (value, max = 100) => ({
    circ: 2 * Math.PI * 52,
    offset: 2 * Math.PI * 52,
    shown: 0,
    init() {
      setTimeout(() => {
        this.offset = this.circ * (1 - Math.max(0, Math.min(1, value / max)));
        const t0 = performance.now();
        const step = (now) => {
          const p = Math.min(1, (now - t0) / 1200);
          this.shown = value * (1 - Math.pow(1 - p, 3));
          if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
        setTimeout(() => { this.shown = value; }, 1600);
      }, 150);
    },
  }));

  /* Chatbot (bloc 4) : RAG Qdrant + Gemini en derja (services/rag/assistant.py), avec la parcelle de la page */
  Alpine.data("chatbot", (url) => {
    const cfg = JSON.parse(document.getElementById("chat-config").textContent);
    return {
      open: false,
      input: "",
      typing: false,
      suggestions: cfg.suggestions,
      messages: [{ role: "bot", text: cfg.welcome }],
      toggle() {
        this.open = !this.open;
        if (this.open) this.$nextTick(() => { icons(); this.$refs.input.focus(); });
      },
      scroll() { this.$nextTick(() => { this.$refs.scroll.scrollTop = this.$refs.scroll.scrollHeight; }); },
      async send(text) {
        const q = (text ?? this.input).trim();
        if (!q || this.typing) return;
        this.messages.push({ role: "user", text: q });
        this.input = "";
        this.typing = true;
        this.scroll();
        try {
          const historique = this.messages.slice(1, -1).slice(-6).map((m) => ({ role: m.role, text: m.text }));
          const [res] = await Promise.all([
            fetch(url, {
              method: "POST",
              headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
              body: JSON.stringify({ q, pid: cfg.pid, historique }),
            }).then((r) => r.json()),
            new Promise((r) => setTimeout(r, 400)),
          ]);
          this.messages.push({ role: "bot", text: res.reply, actions: res.actions || [],
                               sources: res.sources || [], mode: res.mode });
          this.$nextTick(() => icons());
        } catch (e) {
          this.messages.push({ role: "bot", text: UI.chat.error });
        }
        this.typing = false;
        this.scroll();
      },
    };
  });
});
