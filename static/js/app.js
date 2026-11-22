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

function speechFrames(text) {
  const frames = [];
  const words = new Map();
  for (const word of text.matchAll(/[\p{L}\p{M}\p{N}]+|[.,!?;:،؟…]/gu)) {
    const value = word[0].toLowerCase();
    if (!/[\p{L}\p{N}]/u.test(value)) {
      frames.push({ shape: "rest", ms: /[.!?؟…]/.test(value) ? 210 : 100 });
      continue;
    }
    words.set(word.index, frames.length);
    const vowels = value.normalize("NFD").match(/[aoueiwyاويَُِ]/g) || [];
    const shapes = vowels.slice(0, 4).map((vowel) => {
      if (/[ouwوُ]/.test(vowel)) return "round";
      return /[eiyيِ]/.test(vowel) ? "wide" : "open";
    });
    if (!shapes.length) shapes.push("open");
    const duration = Math.min(430, Math.max(110, 65 + value.length * 27));
    for (const shape of shapes) frames.push({ shape, ms: duration / shapes.length });
    frames.push({ shape: "rest", ms: 35 });
  }
  return { frames, words };
}

function fennecRoute(from, to) {
  const dx = from.left - to.left;
  const dy = from.top - to.top;
  const scale = from.height / to.height;
  const arc = Math.min(44, Math.abs(dx) * .05);
  const smooth = (value) => {
    const t = Math.max(0, Math.min(1, value));
    return t * t * (3 - 2 * t);
  };
  return Array.from({ length: 25 }, (_, i) => {
    const t = i / 24;
    const x = dx * (1 - smooth((t - .06) / .88));
    const y = dy * (1 - smooth((t - .10) / .84)) - arc * Math.sin(Math.PI * t) ** 2;
    const size = scale + (1 - scale) * smooth(t);
    return { transform: `translate3d(${x}px, ${y}px, 0) scale(${size})` };
  });
}

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
    const synth = window.speechSynthesis;
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const handoffKey = "kizuna-chat-navigation";
    let utterance = null;
    let recognition = null;
    let pendingSimulation;
    let parcelChoices = [];
    let reactionTimer;
    let mouthTimer;
    let fennec;
    let flight;
    let origin;
    let hovering = false;
    let conversation = 0;
    return {
      open: false,
      input: "",
      typing: false,
      speechAvailable: !!(synth && window.SpeechSynthesisUtterance),
      voiceEnabled: false,
      voiceError: false,
      micAvailable: !!(window.isSecureContext && Recognition),
      micActive: false,
      micStatus: "",
      guided: false,
      emotion: "",
      mouth: "rest",
      suggestions: cfg.suggestions,
      messages: [{ role: "bot", text: cfg.welcome }],
      init() {
        this.$watch("mouth", (shape) => fennec?.setMouth(shape));
        try {
          const handoff = JSON.parse(sessionStorage.getItem(handoffKey));
          sessionStorage.removeItem(handoffKey);
          if (handoff?.path === location.pathname && Date.now() - handoff.time < 20000) {
            this.open = true;
            this.voiceEnabled = this.speechAvailable && handoff.voice;
            this.messages.push(...handoff.messages);
          }
        } catch {
          // Le chat fonctionne aussi quand le stockage navigateur est désactivé.
        }
        this.$nextTick(() => {
          const observer = new ResizeObserver(() => this.placeFennec());
          observer.observe(this.$refs.dock);
          observer.observe(this.$refs.panel.firstElementChild);
          this.showFennec();
          const reply = this.messages.at(-1);
          this.showGuide();
          if (reply.guide && this.open) {
            this.react(reply.reaction || "point");
            this.speak(reply);
            this.scroll();
          }
        });
      },
      toggle() {
        if (this.open) return;
        this.setFennecHover(false);
        origin = this.$refs.fennec.getBoundingClientRect();
        this.open = true;
        this.$nextTick(() => {
          icons();
          this.placeFennec();
          this.showGuide();
        });
      },
      setFennecHover(active) {
        hovering = active && !this.open;
        fennec?.setHover(hovering);
      },
      placeFennec() {
        if (!this.open || flight) return;
        const { fennec: actor, dock, panel, input } = this.$refs;
        const to = dock.getBoundingClientRect();
        if (!to.height) return;
        Object.assign(actor.style, { left: `${to.left}px`, top: `${to.top}px`, bottom: "auto",
          width: `${to.width}px`, height: `${to.height}px` });
        if (!origin) return;
        const from = origin;
        origin = null;
        if (!panel.contains(document.activeElement)) panel.focus({ preventScroll: true });
        const focusInput = () => {
          if (document.activeElement === panel && !window.matchMedia("(pointer: coarse)").matches) {
            input.focus({ preventScroll: true });
          }
        };
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !actor.animate) {
          focusInput();
          return;
        }
        const duration = Math.round(Math.min(1350, Math.max(740, 660 + Math.abs(to.left - from.left) * .55)));
        const animation = actor.animate(fennecRoute(from, to), { duration, fill: "both" });
        flight = animation;
        fennec?.setTravel(animation);
        animation.finished.then(() => {
          if (flight !== animation) return;
          flight = null;
          animation.cancel();
          fennec?.setTravel(null);
          this.placeFennec();
          focusInput();
        }).catch(() => {});
      },
      async showFennec() {
        const stage = this.$refs.fennec;
        try {
          const module = await import(stage.dataset.module);
          fennec = await module.createFennec(stage);
          fennec.setMouth(this.mouth);
          fennec.setTravel(flight);
          fennec.setHover(hovering);
        } catch {
          // Le portrait reste affiché si WebGL est indisponible.
        }
      },
      close() {
        conversation++;
        this.stopListening();
        this.stopSpeech();
        this.micStatus = "";
        pendingSimulation = null;
        parcelChoices = [];
        this.clearGuide();
        flight?.cancel();
        flight = origin = null;
        fennec?.setTravel(null);
        this.$refs.fennec.removeAttribute("style");
        this.open = false;
        this.$nextTick(() => requestAnimationFrame(() => this.$refs.launcher.focus()));
      },
      scroll() { this.$nextTick(() => { this.$refs.scroll.scrollTop = this.$refs.scroll.scrollHeight; }); },
      showGuide() {
        const params = new URLSearchParams(location.search);
        const focus = params.get("chat_focus");
        const map = document.getElementById("diag-map");
        const schedule = document.querySelector("[data-chat-pump-schedule]");
        if ((focus !== "red-zone" || !map) && (focus !== "pump" || !schedule)) return;
        this.guided = this.open;
        this.$nextTick(() => requestAnimationFrame(() => {
          document.querySelector(".chat-highlight")?.classList.remove("chat-highlight");
          const day = focus === "pump" && [...schedule.querySelectorAll("[data-chat-pump-date]")]
            .find((card) => card.dataset.chatPumpDate === params.get("date"));
          if (day) day.click();
          const highlight = focus === "red-zone" ? map : day?.querySelector("[data-chat-pump-slot]") || day || schedule;
          highlight.classList.add("chat-highlight");
          highlight.scrollIntoView({ block: "start", inline: "nearest", behavior: "instant" });
          document.dispatchEvent(new CustomEvent("chat-focus", { detail: focus }));
        }));
      },
      clearGuide() {
        this.guided = false;
        const page = new URL(location.href);
        if (!page.searchParams.has("chat_focus")) return;
        page.searchParams.delete("chat_focus");
        page.searchParams.delete("date");
        history.replaceState(history.state, "", page);
        document.querySelector(".chat-highlight")?.classList.remove("chat-highlight");
        requestAnimationFrame(() => document.dispatchEvent(new CustomEvent("chat-focus")));
      },
      react(emotion) {
        this.emotion = emotion;
        clearTimeout(reactionTimer);
        reactionTimer = setTimeout(() => { this.emotion = ""; }, 1600);
      },
      chooseParcel(action) {
        this.send(action.question, true, action.id, action.label);
      },
      followGuide(event, action, message) {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const url = new URL(action.url, location.href);
        if (!url.searchParams.has("chat_focus") || url.origin !== location.origin) return;
        event.preventDefault();
        if (!this.followPage(url.href, "", message)) {
          this.react(message.reaction || "point");
          this.speak(message);
        }
      },
      readGuide(message) {
        this.voiceEnabled = true;
        this.speak(message);
      },
      stopListening() {
        const current = recognition;
        recognition = null;
        this.micActive = false;
        if (current) current.abort();
      },
      toggleMicrophone() {
        if (!this.micAvailable || this.typing) return;
        if (recognition) {
          recognition.stop();
          return;
        }
        this.stopSpeech();
        this.voiceEnabled = this.speechAvailable;
        this.voiceError = false;
        this.micStatus = "";
        this.micActive = true;
        const current = new Recognition();
        recognition = current;
        current.lang = "fr-FR";
        current.continuous = false;
        current.interimResults = false;
        let transcript = "";
        current.onresult = (event) => {
          transcript = Array.from(event.results).filter((result) => result.isFinal)
            .map((result) => result[0].transcript).join(" ").trim();
        };
        current.onerror = ({ error }) => {
          if (recognition !== current) return;
          recognition = null;
          this.micActive = false;
          this.micStatus = error === "not-allowed" || error === "service-not-allowed"
            ? "Autorisez le microphone dans votre navigateur."
            : error === "no-speech" ? "Je n’ai rien entendu. Réessayez."
            : "La reconnaissance vocale est indisponible. Vous pouvez écrire votre demande.";
        };
        current.onend = () => {
          if (recognition !== current) return;
          recognition = null;
          this.micActive = false;
          this.micStatus = transcript ? "" : "Je n’ai rien entendu. Réessayez.";
          if (transcript && this.open) this.send(transcript, true);
        };
        try {
          current.start();
        } catch {
          current.onerror({ error: "unavailable" });
        }
      },
      stopSpeech() {
        clearTimeout(mouthTimer);
        this.mouth = "rest";
        if (!utterance) return;
        utterance = null;
        synth.cancel();
      },
      toggleVoice() {
        if (!this.speechAvailable) return;
        this.voiceEnabled = !this.voiceEnabled;
        this.voiceError = false;
        if (this.voiceEnabled) {
          this.speak(this.messages.findLast((message) => message.role === "bot"));
        } else {
          this.stopSpeech();
        }
      },
      speak(message) {
        if (!this.open || !this.voiceEnabled || !message?.text) return;
        this.stopSpeech();
        const voiceText = message.text.replace(/\[\d+\]/g, "").trim();
        if (!voiceText) return;
        const current = new window.SpeechSynthesisUtterance(voiceText);
        utterance = current;
        const lang = message.lang || (/\p{Script=Arabic}/u.test(voiceText) ? "ar" : message.mode === "control" ? "en" : "fr");
        const voices = synth.getVoices();
        const matches = voices.filter((voice) => voice.lang.toLowerCase().split(/[-_]/)[0] === lang);
        const voice = matches.find((entry) => entry.lang.toLowerCase() === "ar-tn")
          || matches.find((entry) => entry.localService) || matches[0];
        current.lang = voice?.lang || lang;
        if (voice) current.voice = voice;
        const { frames, words } = speechFrames(voiceText);
        const playFrame = (index) => {
          if (utterance !== current) return;
          clearTimeout(mouthTimer);
          const frame = frames[index];
          this.mouth = frame?.shape || "rest";
          if (frame) mouthTimer = setTimeout(() => playFrame(index + 1), frame.ms);
        };
        const finish = () => {
          if (utterance !== current) return;
          utterance = null;
          clearTimeout(mouthTimer);
          this.mouth = "rest";
        };
        current.onstart = () => playFrame(0);
        current.onboundary = ({ charIndex }) => {
          if (words.has(charIndex)) playFrame(words.get(charIndex));
        };
        current.onend = finish;
        current.onerror = () => {
          if (utterance !== current) return;
          finish();
          this.voiceEnabled = false;
          this.voiceError = true;
        };
        try {
          synth.speak(current);
        } catch {
          current.onerror();
        }
      },
      addReply(reply) {
        const message = { role: "bot", ...reply };
        this.messages.push(message);
        const action = this.messages.at(-1).actions?.find((item) => item.kind === "simulate");
        parcelChoices = reply.actions?.filter((item) => item.kind === "parcel") || [];
        pendingSimulation = action ? { message: this.messages.at(-1), action } : null;
        if (reply.reaction) this.react(reply.reaction);
        this.speak(message);
      },
      followPage(path, question, reply) {
        const destination = new URL(path, location.href);
        if (destination.origin !== location.origin) return false;
        const guide = destination.searchParams.has("chat_focus");
        const message = { role: "bot", text: reply.text, mode: reply.mode, lang: reply.lang, guide, reaction: reply.reaction };
        if (destination.pathname === location.pathname && guide) {
          history.replaceState(history.state, "", destination);
          this.showGuide();
          return false;
        }
        if (destination.href === location.href) return false;
        try {
          sessionStorage.setItem(handoffKey, JSON.stringify({ path: destination.pathname, time: Date.now(),
            voice: this.voiceEnabled, messages: question ? [{ role: "user", text: question }, message] : [message] }));
        } catch {
          // La navigation reste possible sans restaurer le panneau.
        }
        window.location.assign(destination.href);
        return true;
      },
      async simulate(message, action) {
        if (message.mode !== "control" || this.typing || action.used) return;
        this.stopListening();
        this.stopSpeech();
        action.used = true;
        this.typing = true;
        const french = message.lang === "fr";
        let text = french ? "La simulation n’a pas abouti. Réessayez." : UI.chat.error;
        let reaction = "concern";
        try {
          const response = await fetch(action.url, { method: "POST", headers: { "X-CSRFToken": csrfToken() } });
          const result = await response.json();
          if (response.ok && result.ok) {
            reaction = "success";
            text = UI.chat.control_simulated.replace("{day}", result.etat.jours_ecoules)
              .replace("{count}", result.traites.length);
            if (french) text = `Jour ${result.etat.jours_ecoules} sur 7. Événements traités : ${result.traites.length}.`;
            if (result.etat.semaine_finie) text += french ? " La semaine est terminée." : " " + UI.chat.control_week_done;
          } else if (result.message === "validate") {
            text = french ? "Validez le planning dans Irrigation et activez le mode automatique ou manuel." : UI.chat.control_validate;
          }
        } catch {
          // Le message reste visible même si la connexion est interrompue.
        }
        this.addReply({ text, mode: "control", lang: message.lang, reaction });
        this.typing = false;
        this.scroll();
      },
      async send(text, spoken = false, pid = cfg.pid, display = null) {
        let q = (text ?? this.input).trim();
        if (!q || this.typing) return;
        const digits = ["zero", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf"];
        const code = q.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "").split(/[^a-z0-9]+/)
          .map((word) => digits.includes(word) ? digits.indexOf(word) : word).join("").toUpperCase();
        const choice = !display && parcelChoices.find((item) => item.id.replaceAll("-", "").toUpperCase() === code);
        if (choice) {
          display = q;
          q = choice.question;
          pid = choice.id;
          spoken = true;
        }
        parcelChoices = [];
        const currentConversation = conversation;
        this.stopListening();
        this.stopSpeech();
        this.micStatus = "";
        this.messages.push({ role: "user", text: display || q });
        this.input = "";
        const confirmation = pendingSimulation;
        pendingSimulation = null;
        const answer = q.toLowerCase().replace(/[\s.!?,]+$/g, "");
        if (confirmation && !confirmation.action.used && /^(oui|confirme|je confirme|non|annule|annuler)$/.test(answer)) {
          if (/^(oui|confirme|je confirme)$/.test(answer)) {
            await this.simulate(spoken ? { ...confirmation.message, lang: "fr" } : confirmation.message, confirmation.action);
          } else {
            confirmation.action.used = true;
            this.addReply({ text: "Simulation annulée.", mode: "control", lang: "fr" });
            this.scroll();
          }
          return;
        }
        this.typing = true;
        this.scroll();
        try {
          const historique = this.messages.slice(1, -1)
            .filter((m, i, ms) => m.mode !== "control" && ms[i + 1]?.mode !== "control")
            .slice(-6).map((m) => ({ role: m.role, text: m.text }));
          const [res] = await Promise.all([
            fetch(url, {
              method: "POST",
              signal: AbortSignal.timeout(18000),
              headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
              body: JSON.stringify({ q, pid, historique, voice: spoken }),
            }).then((r) => {
              if (!r.ok) throw new Error(`Chat HTTP ${r.status}`);
              return r.json();
            }),
            new Promise((r) => setTimeout(r, 400)),
          ]);
          const guide = res.navigate && new URL(res.navigate, location.href).searchParams.has("chat_focus");
          const reply = { text: res.reply, actions: res.actions || [], sources: res.sources || [], mode: res.mode,
            guide, reaction: res.reaction || (guide ? "point" : null), lang: res.mode === "local" || (spoken && res.mode === "control") ? "fr" : undefined };
          const redirected = this.open && currentConversation === conversation && res.navigate &&
            (guide || (spoken && res.mode === "control")) && this.followPage(res.navigate, display || q, reply);
          if (!redirected) {
            this.addReply(reply);
            this.$nextTick(() => icons());
          }
        } catch (e) {
          this.addReply(e.name === "TimeoutError"
            ? { text: "La réponse tarde à arriver. Vous pouvez réessayer.", lang: "fr" }
            : { text: UI.chat.error });
        } finally {
          this.typing = false;
          this.scroll();
        }
      },
    };
  });
});
