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

  /* WAV PCM 16 bits, mono, 16 kHz (format attendu par Azure Speech) à partir des échantillons du micro */
  window.wav16k = function (morceaux, freq) {
    const n = morceaux.reduce((s, m) => s + m.length, 0);
    const tout = new Float32Array(n);
    let o = 0;
    for (const m of morceaux) { tout.set(m, o); o += m.length; }
    const ratio = freq / 16000, len = Math.floor(n / ratio);
    const pcm = new Int16Array(len);
    for (let i = 0; i < len; i++) {
      const v = Math.max(-1, Math.min(1, tout[Math.floor(i * ratio)] || 0));
      pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
    }
    const buf = new ArrayBuffer(44 + pcm.length * 2), d = new DataView(buf);
    const ecrire = (p, s) => { for (let i = 0; i < s.length; i++) d.setUint8(p + i, s.charCodeAt(i)); };
    ecrire(0, "RIFF"); d.setUint32(4, 36 + pcm.length * 2, true); ecrire(8, "WAVE"); ecrire(12, "fmt ");
    d.setUint32(16, 16, true); d.setUint16(20, 1, true); d.setUint16(22, 1, true); d.setUint32(24, 16000, true);
    d.setUint32(28, 32000, true); d.setUint16(32, 2, true); d.setUint16(34, 16, true); ecrire(36, "data");
    d.setUint32(40, pcm.length * 2, true);
    new Int16Array(buf, 44).set(pcm);
    return new Blob([buf], { type: "audio/wav" });
  };

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

      /* ── Voix (tounsi) : enregistrement WAV 16 kHz mono -> /chat/voice/ -> réponse lue par la voix tunisienne ── */
      recording: false, rec: null, speaking: false,
      async micro() {
        if (this.recording) return this.stopRec();
        if (this.typing) return;
        try {
          const flux = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
          const ctx = new (window.AudioContext || window.webkitAudioContext)();
          const source = ctx.createMediaStreamSource(flux);
          const proc = ctx.createScriptProcessor(4096, 1, 1);
          const morceaux = [];
          proc.onaudioprocess = (e) => morceaux.push(new Float32Array(e.inputBuffer.getChannelData(0)));
          source.connect(proc); proc.connect(ctx.destination);
          this.rec = { flux, ctx, source, proc, morceaux, minuteur: setTimeout(() => this.stopRec(), 30000) };
          this.recording = true;
          this.stopVoice();
        } catch (e) {
          this.messages.push({ role: "bot", text: UI.chat.mic_error });
          this.scroll();
        }
      },
      stopRec() {
        const r = this.rec;
        if (!r) return;
        clearTimeout(r.minuteur);
        r.proc.disconnect(); r.source.disconnect(); r.flux.getTracks().forEach((t) => t.stop());
        const wav = wav16k(r.morceaux, r.ctx.sampleRate);
        r.ctx.close();
        this.rec = null; this.recording = false;
        if (wav.size > 2000) this.sendAudio(wav);
      },
      async sendAudio(wav) {
        const iUser = this.messages.push({ role: "user", text: "🎤 …" }) - 1;
        const msgUser = this.messages[iUser];   // objet réactif (Alpine) : la transcription s'affichera
        this.typing = true;
        this.scroll();
        const fd = new FormData();
        fd.append("audio", wav, "voix.wav");
        fd.append("pid", cfg.pid || "");
        fd.append("historique", JSON.stringify(this.messages.slice(1, -1).slice(-6).map((m) => ({ role: m.role, text: m.text }))));
        try {
          const r = await fetch(cfg.voiceUrl, { method: "POST", headers: { "X-CSRFToken": csrfToken() }, body: fd });
          const res = await r.json();
          if (!r.ok) throw new Error(res.detail || res.error);
          msgUser.text = "🎤 " + res.transcription;
          const m = { role: "bot", text: res.reply, a_dire: res.a_dire, actions: res.actions || [],
                      sources: res.sources || [], mode: res.mode };
          this.messages.push(m);
          this.$nextTick(() => icons());
          this.playVoice(res.audio, res.a_dire || res.reply, res.audio_mime);
        } catch (e) {
          msgUser.text = "🎤 (…)";
          this.messages.push({ role: "bot", text: UI.chat.voice_error });
        }
        this.typing = false;
        this.scroll();
      },
      async speak(m) {
        if (this.speaking) return this.stopVoice();
        try {
          this.speaking = true;   // la voix tunisienne peut prendre ~15 s (Lahgtna)
          const r = await fetch(cfg.ttsUrl, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
                                             body: JSON.stringify({ text: m.text, a_dire: m.a_dire || "" }) }).then((x) => x.json());
          this.playVoice(r.audio, m.a_dire || m.text, r.audio_mime);
        } catch (e) { this.playVoice(null, m.a_dire || m.text); }
      },
      playVoice(audioB64, texte, mime) {
        this.stopVoice();
        if (audioB64) {   // voix tunisienne : Lahgtna (WAV) ou edge-tts / Azure (MP3)
          this._audio = new Audio("data:" + (mime || "audio/mpeg") + ";base64," + audioB64);
          this._audio.onended = () => { this.speaking = false; };
          this.speaking = true;
          this._audio.play().catch(() => { this.speaking = false; });
        } else if (window.speechSynthesis && texte) {   // secours : voix arabe du navigateur
          const u = new SpeechSynthesisUtterance(texte);
          const voix = speechSynthesis.getVoices();
          u.voice = voix.find((v) => v.lang === "ar-TN") || voix.find((v) => v.lang.startsWith("ar")) || null;
          u.lang = u.voice ? u.voice.lang : "ar";
          u.onend = () => { this.speaking = false; };
          this.speaking = true;
          speechSynthesis.speak(u);
        }
      },
      stopVoice() {
        if (this._audio) { this._audio.pause(); this._audio = null; }
        if (window.speechSynthesis) speechSynthesis.cancel();
        this.speaking = false;
      },
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
