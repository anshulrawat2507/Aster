"use strict";

// Presentation only: voice.js owns the microphone, WebRTC connection and call lifecycle.
(() => {
  const get = (id) => document.getElementById(id);
  const dialog = get("call-dialog");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const ui = { active: false, connectedAt: null, timer: null, elapsed: 0, speaking: false, muted: false, input: 0, inputAt: 0, timezone: "Asia/Kolkata", changes: new Set(), lastAppointment: null };
  const fx = { context: null, source: null, analyser: null, silent: null, data: null, frame: null, ring: null, tones: new Set(), lastPaint: 0 };
  let sounds = true;
  try { sounds = localStorage.getItem("aster-call-sounds") !== "off"; } catch { /* Optional preference. */ }
  const waveform = get("call-waveform");
  const bars = Array.from({ length: 25 }, () => document.createElement("i"));
  waveform.replaceChildren(...bars);

  function node(tag, className, text) {
    const item = document.createElement(tag);
    item.className = className;
    item.textContent = text;
    return item;
  }
  function duration(seconds) {
    return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  }
  function updateTimer() {
    ui.elapsed = ui.connectedAt === null ? 0 : Math.floor((performance.now() - ui.connectedAt) / 1000);
    get("call-timer").textContent = duration(ui.elapsed);
    get("call-timer").dateTime = `PT${ui.elapsed}S`;
  }
  function tone(frequency, length, delay = 0) {
    if (!sounds || fx.context?.state !== "running") return;
    const context = fx.context;
    const oscillator = context.createOscillator();
    const volume = context.createGain();
    const when = context.currentTime + delay;
    oscillator.frequency.value = frequency;
    volume.gain.setValueAtTime(0, when);
    volume.gain.linearRampToValueAtTime(.025, when + .025);
    volume.gain.setValueAtTime(.025, when + length - .04);
    volume.gain.linearRampToValueAtTime(0, when + length);
    oscillator.connect(volume).connect(context.destination);
    fx.tones.add(oscillator);
    oscillator.onended = () => { fx.tones.delete(oscillator); oscillator.disconnect(); volume.disconnect(); };
    oscillator.start(when);
    oscillator.stop(when + length);
  }
  function stopTones() {
    clearInterval(fx.ring);
    fx.ring = null;
    for (const oscillator of fx.tones) { try { oscillator.stop(); } catch { /* Already ended. */ } }
    fx.tones.clear();
  }
  function startRinging() {
    stopTones();
    const ring = () => {
      if (ui.active && dialog.dataset.phase === "connecting") { tone(440, .45); tone(480, .45); }
    };
    ring();
    fx.ring = setInterval(ring, 3000);
  }
  function drawWave(now) {
    if (!ui.active) return;
    fx.frame = requestAnimationFrame(drawWave);
    if (now - fx.lastPaint < (reducedMotion.matches ? 250 : 33)) return;
    fx.lastPaint = now;
    const input = !ui.muted && now - ui.inputAt < 650 ? ui.input : 0;
    if (ui.speaking && fx.analyser) fx.analyser.getByteFrequencyData(fx.data);
    let peak = 0;
    bars.forEach((bar, index) => {
      // Input is measured by the server; output comes from the remote audio stream.
      const output = ui.speaking && fx.data ? fx.data[2 + index * 3] / 255 : 0;
      const level = Math.max(output, input * (.3 + .7 * Math.sin(Math.PI * (index + 1) / 26)));
      peak = Math.max(peak, level);
      bar.style.height = `${3 + level * 31}px`;
    });
    waveform.dataset.level = peak.toFixed(3);
    waveform.dataset.source = ui.speaking ? "assistant" : "microphone";
  }
  function initAudio() {
    try {
      const Context = window.AudioContext || window.webkitAudioContext;
      fx.context = new Context();
      void fx.context.resume().catch(() => {});
    } catch { /* Calls still work through the native audio element. */ }
    fx.frame = requestAnimationFrame(drawWave);
  }
  function phase(value) {
    dialog.dataset.phase = value;
    get("connection-state").textContent = { permission: "Microphone access", connecting: "Calling clinic", connected: "Connected", ended: "Call ended", error: "Could not connect" }[value] || "Ready to call";
    if (value === "connecting") startRinging();
    else stopTones();
  }
  function setMuted(muted) {
    ui.muted = muted;
    dialog.dataset.muted = String(muted);
    get("mute-label").textContent = muted ? "Unmute" : "Mute";
    get("mute-call").setAttribute("aria-label", muted ? "Unmute microphone" : "Mute microphone");
    get("mute-icon").setAttribute("href", muted ? "#i-mic-off" : "#i-mic");
  }
  function start() {
    ui.active = true;
    ui.connectedAt = null;
    ui.elapsed = 0;
    ui.speaking = false;
    ui.input = 0;
    ui.changes.clear();
    ui.lastAppointment = null;
    clearInterval(ui.timer);
    updateTimer();
    setMuted(false);
    dialog.dataset.mode = "waiting";
    get("live-call-actions").hidden = false;
    get("ended-call-actions").hidden = true;
    get("call-summary").hidden = true;
    get("call-receipt").hidden = true;
    get("call-receipt").replaceChildren();
    get("audio-settings").open = false;
    document.querySelector(".phone-body").scrollTop = 0;
    get("transcript-state").textContent = "Just this call";
    get("caller-name").textContent = "You · Guest caller";
    get("call-transcript").replaceChildren(node("p", "transcript-placeholder", "A little less waiting. A little more care. Your conversation will appear here."));
    phase("permission");
    initAudio();
  }
  function connected() {
    phase("connected");
    if (ui.connectedAt === null) {
      ui.connectedAt = performance.now();
      updateTimer();
      ui.timer = setInterval(updateTimer, 1000);
    }
  }
  function remoteStream(stream) {
    if (!fx.context) return;
    try {
      fx.source?.disconnect(); fx.analyser?.disconnect(); fx.silent?.disconnect();
      fx.source = fx.context.createMediaStreamSource(stream);
      fx.analyser = fx.context.createAnalyser();
      fx.analyser.fftSize = 512;
      fx.analyser.smoothingTimeConstant = .65;
      fx.data = new Uint8Array(fx.analyser.frequencyBinCount);
      fx.silent = fx.context.createGain();
      fx.silent.gain.value = 0;
      // The audio element plays the voice; this silent graph only measures it.
      fx.source.connect(fx.analyser).connect(fx.silent).connect(fx.context.destination);
    } catch { /* Input animation remains available. */ }
  }
  function mode(value) { dialog.dataset.mode = value; ui.speaking = value === "speaking"; }
  function receipt(message) {
    const appointment = message.appointment;
    if (!["booked", "cancelled"].includes(message.action) || !appointment?.id || !Number.isFinite(Date.parse(appointment.starts_at))) return;
    ui.changes.add(`${message.action}:${appointment.id}`);
    ui.lastAppointment = appointment.id;
    const booked = message.action === "booked";
    const card = get("call-receipt");
    card.dataset.action = message.action;
    const title = node("div", "receipt-title", "");
    title.append(node("span", "receipt-mark", booked ? "✓" : "−"), node("strong", "", booked ? "You’re booked." : "Appointment cancelled."));
    const when = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZoneName: "short", timeZone: ui.timezone }).format(new Date(appointment.starts_at));
    card.replaceChildren(title, node("p", "receipt-doctor", appointment.doctor_name), node("p", "receipt-date", when), node("p", "receipt-note", "Confirmed by the clinic · Saved to your schedule"));
    card.hidden = false;
    const digits = (appointment.phone_masked || "").replace(/\D/g, "").slice(-4);
    if (digits) get("caller-name").textContent = `You · Caller ending ${digits}`;
    if (!reducedMotion.matches) card.animate([{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 300 });
    card.scrollIntoView({ block: "nearest", behavior: reducedMotion.matches ? "instant" : "smooth" });
  }
  function finish(message, error) {
    updateTimer();
    clearInterval(ui.timer);
    ui.active = false;
    ui.speaking = false;
    phase(error && ui.connectedAt === null ? "error" : "ended");
    cancelAnimationFrame(fx.frame);
    bars.forEach(bar => { bar.style.height = "3px"; });
    waveform.dataset.level = "0";
    get("transcript-state").textContent = "Call complete";
    get("live-call-actions").hidden = true;
    get("ended-call-actions").hidden = false;
    get("call-summary").hidden = false;
    get("call-summary").textContent = ui.connectedAt === null ? "No connection established. You can try again when you’re ready." : `${duration(ui.elapsed)} together${ui.changes.size ? ` · ${ui.changes.size} appointment update${ui.changes.size === 1 ? "" : "s"}` : " · Thanks for calling Aster."}`;
    if (ui.connectedAt !== null) { tone(520, .14); tone(300, .14, .1); }
    fx.source?.disconnect(); fx.analyser?.disconnect(); fx.silent?.disconnect();
    fx.source = fx.analyser = fx.silent = fx.data = null;
    const oldContext = fx.context;
    fx.context = null;
    setTimeout(() => { if (oldContext && oldContext.state !== "closed") void oldContext.close().catch(() => {}); }, 300);
    get("audio-settings").open = false;
    document.querySelector(".phone-body").scrollTop = 0;
  }
  function updateSoundButton() {
    get("call-sounds").setAttribute("aria-pressed", String(sounds));
    get("call-sounds").setAttribute("aria-label", sounds ? "Turn call sounds off" : "Turn call sounds on");
    get("call-sounds").title = sounds ? "Call sounds on" : "Call sounds off";
  }
  get("call-sounds").addEventListener("click", () => {
    sounds = !sounds;
    try { localStorage.setItem("aster-call-sounds", sounds ? "on" : "off"); } catch { /* Optional preference. */ }
    updateSoundButton();
    if (!sounds) stopTones();
    else if (dialog.dataset.phase === "connecting") startRinging();
  });
  updateSoundButton();
  get("audio-settings-toggle").addEventListener("click", () => {
    const settings = get("audio-settings");
    settings.open = !settings.open;
    if (settings.open) settings.scrollIntoView({ block: "nearest", behavior: reducedMotion.matches ? "instant" : "smooth" });
  });
  get("audio-settings").addEventListener("toggle", () => get("audio-settings-toggle").setAttribute("aria-expanded", String(get("audio-settings").open)));
  get("call-done").addEventListener("click", () => {
    dialog.close();
    if (ui.lastAppointment) document.dispatchEvent(new CustomEvent("aster:focus-appointment", { detail: { id: ui.lastAppointment } }));
  });
  window.asterCallUI = {
    start, phase, connected, remoteStream, mode, receipt, finish, setMuted,
    input(level) { ui.input = Math.max(0, Math.min(1, Number(level) || 0)); ui.inputAt = performance.now(); },
    setTimezone(zone) { ui.timezone = zone; },
    resumeAudio() { return fx.context?.resume().catch(() => {}); },
  };
})();
