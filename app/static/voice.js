"use strict";

// Browser-native WebRTC carries real microphone audio. No browser STT or TTS.
(() => {
  const get = (id) => document.getElementById(id);
  const startButton = document.querySelector(".call-button");
  const badge = document.querySelector(".setup-tag");
  const dialog = get("call-dialog");
  const audio = get("assistant-audio");
  const experience = window.asterCallUI;
  const call = { ready: false, active: false, generation: 0, pc: null, stream: null, channel: null, id: null, ping: null, timeout: null, assistant: null, muted: false };
  const microphone = { timer: null, startedAt: 0, lastAudioAt: 0, lastSoundAt: 0, lastTranscriptAt: 0, switching: false };
  const microphoneSelect = get("microphone-select");

  function microphoneConstraints(deviceId = microphoneSelect.value) {
    return { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: { ideal: 1 }, ...(deviceId ? { deviceId: { exact: deviceId } } : {}) }, video: false };
  }

  async function listMicrophones() {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const selected = call.stream?.getAudioTracks()[0]?.getSettings().deviceId || microphoneSelect.value;
      const defaultLabel = devices.find(device => device.kind === "audioinput" && device.deviceId === "default")?.label;
      microphoneSelect.replaceChildren(new Option(defaultLabel || "System default microphone", ""));
      for (const device of devices.filter(item => item.kind === "audioinput" && item.deviceId && !["default", "communications"].includes(item.deviceId))) {
        microphoneSelect.add(new Option(device.label || `Microphone ${microphoneSelect.options.length}`, device.deviceId));
      }
      microphoneSelect.value = [...microphoneSelect.options].some(option => option.value === selected) ? selected : "";
    } catch { /* Keep the current choice if the browser cannot list devices. */ }
  }

  function microphoneHint() {
    const hint = get("microphone-hint");
    const now = performance.now();
    const track = call.stream?.getAudioTracks()[0];
    let warning = false;
    let text = "Speak naturally, then pause briefly for a reply.";
    if (!call.active) text = "Start a call to check your microphone.";
    else if (microphone.switching) text = "Switching microphone…";
    else if (call.muted) text = "Microphone is muted. Unmute to speak.";
    else if (!track) text = "Waiting for microphone access…";
    else if (track.muted) { text = "The browser is not receiving sound from this microphone. Check your laptop's microphone mute key."; warning = true; }
    else if (now - microphone.startedAt > 10000 && (!microphone.lastAudioAt || now - microphone.lastAudioAt > 4000)) {
      text = "Microphone audio is not reaching the call. Choose another input or start a new call."; warning = true;
    } else if (now - microphone.startedAt > 12000 && now - (microphone.lastSoundAt || microphone.startedAt) > 12000) {
      text = "No sound detected. Choose your laptop microphone and check its input volume in Windows sound settings."; warning = true;
    } else if (microphone.lastSoundAt && now - microphone.lastSoundAt < 1800) {
      if (now - microphone.startedAt > 20000 && microphone.lastTranscriptAt < microphone.startedAt) {
        text = "Sound is reaching Aster, but speech has not been recognized yet. Try a short sentence in English."; warning = true;
      } else text = "Sound is reaching Aster.";
    } else if (!microphone.lastAudioAt) text = "Checking microphone audio…";
    if (warning && !hint.classList.contains("warning")) get("audio-settings").open = true;
    hint.textContent = text;
    hint.classList.toggle("warning", warning);
    if (!call.active || call.muted || !microphone.lastAudioAt || now - microphone.lastAudioAt > 1500) get("microphone-level").value = 0;
  }

  function watchMicrophone(stream, generation) {
    const track = stream.getAudioTracks()[0];
    if (!track) throw new Error("The selected device did not provide a microphone track.");
    track.addEventListener("ended", () => {
      if (call.active && generation === call.generation && call.stream === stream) finish("Microphone disconnected", "Reconnect your microphone and start a new call.");
    });
    track.addEventListener("mute", microphoneHint);
    track.addEventListener("unmute", microphoneHint);
    microphone.startedAt = performance.now();
    microphone.lastAudioAt = microphone.lastSoundAt = 0;
    clearInterval(microphone.timer);
    microphone.timer = setInterval(microphoneHint, 1000);
    microphoneSelect.disabled = false;
    void listMicrophones();
    microphoneHint();
  }

  async function switchMicrophone() {
    if (!call.active || !call.pc || microphone.switching) return;
    const generation = call.generation;
    const previous = call.stream;
    let replacement;
    microphone.switching = true;
    microphoneSelect.disabled = true;
    microphoneHint();
    try {
      replacement = await navigator.mediaDevices.getUserMedia(microphoneConstraints());
      if (generation !== call.generation) { replacement.getTracks().forEach(track => track.stop()); return; }
      const track = replacement.getAudioTracks()[0];
      if (!track) throw new Error("No audio track");
      track.enabled = !call.muted;
      const sender = call.pc.getSenders().find(item => item.track?.kind === "audio");
      if (!sender) throw new Error("No audio sender");
      await sender.replaceTrack(track);
      if (generation !== call.generation) { replacement.getTracks().forEach(item => item.stop()); return; }
      call.stream = replacement;
      previous?.getTracks().forEach(item => item.stop());
      watchMicrophone(replacement, generation);
    } catch {
      replacement?.getTracks().forEach(track => track.stop());
      if (generation === call.generation && call.active) {
        await listMicrophones();
        get("microphone-hint").textContent = "Could not open that microphone. Your previous microphone is still selected.";
        get("microphone-hint").classList.add("warning");
      }
    } finally {
      if (generation === call.generation) {
        microphone.switching = false;
        microphoneSelect.disabled = !call.active;
      }
    }
  }

  function updateReadiness(status) {
    call.ready = status?.ready === true;
    startButton.disabled = !call.ready || call.active;
    get("call-again").disabled = !call.ready || call.active;
    badge.textContent = call.active ? "In a call" : call.ready ? "Ready to call" : "Setup pending";
    get("voice-note").textContent = call.ready ? "A conversation, at your pace." : "Finish voice setup to enable calling.";
  }

  function status(text) { get("call-status").textContent = text; }

  function appendTranscript(role, text) {
    const transcript = get("call-transcript");
    transcript.querySelector(".transcript-placeholder")?.remove();
    const entry = document.createElement("p");
    entry.className = `transcript-entry ${role}`;
    const label = document.createElement("strong");
    label.textContent = role === "user" ? "YOU" : "ASTER";
    const body = document.createElement("span");
    body.textContent = text;
    entry.append(label, body);
    transcript.append(entry);
    // Keep the visible transcript bounded for long calls. Nothing is persisted.
    while (transcript.children.length > 100) transcript.firstElementChild.remove();
    transcript.scrollTop = transcript.scrollHeight;
    return body;
  }

  function handleMessage(event) {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (!call.active) return;
    if (message.type === "call_ready") {
      clearTimeout(call.timeout);
      experience.connected();
      status("Connected · Aster is here to help");
      get("mute-call").disabled = false;
    } else if (message.type === "transcript" && message.role === "user") {
      microphone.lastTranscriptAt = performance.now();
      if (message.final) {
        appendTranscript("user", message.text);
        get("interim-transcript").textContent = "";
        call.assistant = null;
        experience.mode("thinking");
        status("Aster is thinking…");
      } else {
        get("interim-transcript").textContent = message.text;
        experience.mode("listening");
        status("Hearing you…");
      }
    } else if (message.type === "input_audio") {
      microphone.lastAudioAt = performance.now();
      if (message.has_sound) microphone.lastSoundAt = microphone.lastAudioAt;
      get("microphone-level").value = call.muted ? 0 : Math.max(0, Math.min(1, Number(message.level) || 0));
      experience.input(message.level);
      microphoneHint();
    } else if (message.type === "assistant_text") {
      if (!call.assistant) call.assistant = appendTranscript("assistant", "");
      call.assistant.textContent += `${call.assistant.textContent ? " " : ""}${message.text}`;
      get("call-transcript").scrollTop = get("call-transcript").scrollHeight;
    } else if (message.type === "speaking") {
      experience.mode(message.speaking ? "speaking" : "listening");
      status(message.speaking ? "Aster is speaking…" : "Listening to you…");
      if (!message.speaking) call.assistant = null;
    } else if (message.type === "interrupted") {
      call.assistant = null;
      experience.mode("listening");
      status("Listening to you…");
    } else if (message.type === "appointment_updated") {
      experience.receipt(message);
      document.dispatchEvent(new CustomEvent("aster:appointments-updated", { detail: { action: message.action, appointment: message.appointment } }));
    } else if (message.type === "error") {
      finish("Call ended", message.message);
    } else if (message.type === "call_ended") {
      finish(message.message || "Call ended");
    } else if (message.type === "signalling" && message.message?.type === "peerLeft") {
      finish("Call ended");
    }
  }

  async function endOnServer(id) {
    if (!id) return;
    try { await fetch(`/api/voice/calls/${encodeURIComponent(id)}/end`, { method: "POST", keepalive: true }); } catch { /* Closing the peer also ends the server session. */ }
  }

  function finish(message = "Call ended", error = "") {
    if (!call.active) return;
    call.active = false;
    call.generation += 1;
    microphone.switching = false;
    clearInterval(call.ping);
    clearTimeout(call.timeout);
    clearInterval(microphone.timer);
    if (call.channel?.readyState === "open") call.channel.send(JSON.stringify({ type: "end_call" }));
    call.stream?.getTracks().forEach((track) => track.stop());
    call.pc?.close();
    void endOnServer(call.id);
    call.id = null;
    call.stream = null;
    call.pc = null;
    call.channel = null;
    call.assistant = null;
    microphoneSelect.disabled = true;
    microphoneHint();
    audio.pause();
    audio.srcObject = null;
    get("enable-call-audio").hidden = true;
    get("interim-transcript").textContent = "";
    get("mute-call").disabled = true;
    get("end-call").disabled = true;
    get("call-error").textContent = error;
    get("call-error").hidden = !error;
    status(message);
    experience.finish(message, error);
    updateReadiness({ ready: call.ready });
  }

  function gatheredIce(pc) {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pc.removeEventListener("icegatheringstatechange", check); reject(new Error("The browser could not prepare its audio connection. Try again.")); }, 8000);
      function check() {
        if (pc.iceGatheringState === "complete") {
          clearTimeout(timer);
          pc.removeEventListener("icegatheringstatechange", check);
          resolve();
        }
      }
      pc.addEventListener("icegatheringstatechange", check);
      check();
    });
  }

  async function start() {
    if (call.active || !call.ready) return;
    call.active = true;
    const generation = ++call.generation;
    call.muted = false;
    call.assistant = null;
    microphone.lastTranscriptAt = 0;
    microphone.startedAt = performance.now();
    microphone.lastAudioAt = microphone.lastSoundAt = 0;
    get("mute-call").setAttribute("aria-pressed", "false");
    get("mute-call").disabled = true;
    get("end-call").disabled = false;
    get("call-error").hidden = true;
    get("call-transcript").replaceChildren();
    if (!dialog.open) dialog.showModal();
    experience.start();
    updateReadiness({ ready: call.ready });
    status("Allow your microphone to begin…");
    call.timeout = setTimeout(() => finish("Could not connect", "The call took too long to start. Please try again."), 45000);
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) {
        throw new Error("Use a current Chrome or Edge browser on localhost (or HTTPS) to make a call.");
      }
      const stream = await navigator.mediaDevices.getUserMedia(microphoneConstraints());
      if (generation !== call.generation) { stream.getTracks().forEach((track) => track.stop()); return; }
      call.stream = stream;
      watchMicrophone(stream, generation);
      experience.phase("connecting");
      const pc = new RTCPeerConnection({ iceServers: [], bundlePolicy: "max-bundle" });
      call.pc = pc;
      for (const track of stream.getAudioTracks()) pc.addTrack(track, stream);
      const channel = pc.createDataChannel("aster-events");
      call.channel = channel;
      channel.onmessage = handleMessage;
      channel.onopen = () => {
        if (generation !== call.generation) return;
        channel.send("ping");
        call.ping = setInterval(() => { if (channel.readyState === "open") channel.send("ping"); }, 1000);
      };
      channel.onclose = () => { if (generation === call.generation && call.active) finish("Call ended"); };
      pc.ontrack = (event) => {
        if (generation !== call.generation) return;
        audio.srcObject = event.streams[0] || new MediaStream([event.track]);
        experience.remoteStream(audio.srcObject);
        audio.play().catch(() => { get("enable-call-audio").hidden = false; });
      };
      pc.onconnectionstatechange = () => {
        if (generation !== call.generation) return;
        if (pc.connectionState === "failed" || pc.connectionState === "disconnected") finish("Connection lost", "The audio connection was interrupted. Please start a new call.");
        else if (pc.connectionState === "connected") status("Starting your assistant…");
      };
      status("Connecting your call…");
      await pc.setLocalDescription(await pc.createOffer());
      await gatheredIce(pc);
      if (generation !== call.generation) return;
      // Let an in-flight offer finish after hang-up so its server call ID can be closed.
      const response = await fetch("/api/voice/offer", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sdp: pc.localDescription.sdp, type: "offer" }),
        signal: AbortSignal.timeout(35000),
      });
      const answer = await response.json();
      if (generation !== call.generation) { if (answer.call_id) await endOnServer(answer.call_id); return; }
      if (!response.ok) throw new Error(answer.error?.message || "The call could not start. Please try again.");
      call.id = answer.call_id;
      await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type });
    } catch (error) {
      if (generation !== call.generation) return;
      const message = error.name === "NotAllowedError" ? "Microphone permission was denied. Allow microphone access in your browser, then try again."
        : error.name === "NotFoundError" ? "No microphone was found. Connect one and try again."
        : error.name === "NotReadableError" ? "Your microphone is busy or unavailable. Close other audio apps and try again."
        : error.name === "TimeoutError" ? "The voice server took too long to respond. Please try again."
        : error.message || "Could not connect the call.";
      finish("Could not connect", message);
    }
  }

  startButton.addEventListener("click", start);
  get("call-again").addEventListener("click", start);
  get("end-call").addEventListener("click", () => finish());
  get("close-call").addEventListener("click", () => { if (call.active) finish(); dialog.close(); });
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); if (call.active) finish(); dialog.close(); });
  get("mute-call").addEventListener("click", () => {
    if (!call.stream) return;
    call.muted = !call.muted;
    call.stream.getAudioTracks().forEach((track) => { track.enabled = !call.muted; });
    experience.setMuted(call.muted);
    get("mute-call").setAttribute("aria-pressed", String(call.muted));
    microphoneHint();
  });
  microphoneSelect.addEventListener("change", switchMicrophone);
  navigator.mediaDevices?.addEventListener?.("devicechange", () => { if (call.active && !microphone.switching) void listMicrophones(); });
  get("enable-call-audio").addEventListener("click", async () => {
    try { await experience.resumeAudio(); await audio.play(); get("enable-call-audio").hidden = true; } catch { status("Audio could not play. Check your speaker settings."); }
  });
  window.addEventListener("pagehide", () => { if (call.active) finish(); });
  window.asterVoice = { updateReadiness };
})();
