(() => {
  const center = document.querySelector("[data-notification-center]");
  if (!center) return;

  const list = center.querySelector("[data-notification-list]");
  const count = center.querySelector("[data-notification-count]");
  const soundToggle = center.querySelector("[data-sound-toggle]");
  const acknowledge = center.querySelector("[data-notification-ack]");
  const storagePrefix = `emporio-attendance:${window.location.host}:`;
  const readKey = `${storagePrefix}read`;
  const heardKey = `${storagePrefix}heard`;
  const soundKey = `${storagePrefix}sound`;
  let events = [];
  let audioContext = null;

  const readSet = (key) => {
    try { return new Set(JSON.parse(localStorage.getItem(key) || "[]")); }
    catch (_error) { return new Set(); }
  };
  const writeSet = (key, values) => {
    try { localStorage.setItem(key, JSON.stringify([...values].slice(-300))); }
    catch (_error) { /* O visual continua mesmo sem armazenamento local. */ }
  };
  const soundEnabled = () => localStorage.getItem(soundKey) === "1";
  const updateSoundLabel = () => {
    soundToggle.textContent = soundEnabled() ? "Desativar som" : "Ativar som";
    soundToggle.setAttribute("aria-pressed", soundEnabled() ? "true" : "false");
  };
  const typeLabel = {
    new_request: "Nova solicitação",
    new_order: "Novo pedido",
    late_order: "Pedido atrasado",
  };

  const render = () => {
    const read = readSet(readKey);
    const unread = events.filter((event) => !read.has(event.id)).length;
    count.textContent = String(unread);
    count.hidden = unread === 0;
    list.replaceChildren();
    if (!events.length) {
      const empty = document.createElement("p");
      empty.className = "notification-empty";
      empty.textContent = "Nenhuma notificação recente.";
      list.append(empty);
      return;
    }
    events.forEach((event) => {
      const link = document.createElement("a");
      link.className = `notification-item notification-${event.type}`;
      if (!read.has(event.id)) link.classList.add("is-unread");
      link.href = event.url;
      const kind = document.createElement("strong");
      kind.textContent = typeLabel[event.type] || "Notificação";
      const label = document.createElement("span");
      label.textContent = event.label;
      const time = document.createElement("time");
      time.dateTime = event.occurred_at;
      time.textContent = new Intl.DateTimeFormat("pt-BR", {
        dateStyle: "short", timeStyle: "short",
      }).format(new Date(event.occurred_at));
      link.append(kind, label, time);
      list.append(link);
    });
  };

  const playOnce = async () => {
    if (!soundEnabled()) return;
    const heard = readSet(heardKey);
    const pending = events.filter((event) => !heard.has(event.id));
    if (!pending.length) return;
    try {
      audioContext ||= new (window.AudioContext || window.webkitAudioContext)();
      await audioContext.resume();
      const oscillator = audioContext.createOscillator();
      const gain = audioContext.createGain();
      oscillator.frequency.value = 660;
      gain.gain.setValueAtTime(0.045, audioContext.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioContext.currentTime + 0.18);
      oscillator.connect(gain).connect(audioContext.destination);
      oscillator.start();
      oscillator.stop(audioContext.currentTime + 0.18);
      pending.forEach((event) => heard.add(event.id));
      writeSet(heardKey, heard);
    } catch (_error) { updateSoundLabel(); }
  };

  const poll = async () => {
    try {
      const response = await fetch(center.dataset.endpoint, {
        credentials: "same-origin", headers: { Accept: "application/json" }, cache: "no-store",
      });
      if (!response.ok) return;
      const payload = await response.json();
      events = Array.isArray(payload.events) ? payload.events : [];
      render();
      await playOnce();
    } catch (_error) { /* Polling silencioso; o próximo ciclo tenta novamente. */ }
  };

  soundToggle.addEventListener("click", async () => {
    const enable = !soundEnabled();
    localStorage.setItem(soundKey, enable ? "1" : "0");
    updateSoundLabel();
    if (enable) await playOnce();
  });
  acknowledge.addEventListener("click", () => {
    const ids = new Set(events.map((event) => event.id));
    writeSet(readKey, ids);
    const heard = readSet(heardKey);
    ids.forEach((id) => heard.add(id));
    writeSet(heardKey, heard);
    render();
  });
  center.addEventListener("toggle", () => {
    if (center.open) {
      const read = readSet(readKey);
      events.forEach((event) => read.add(event.id));
      writeSet(readKey, read);
      render();
    }
  });

  updateSoundLabel();
  poll();
  window.setInterval(poll, 25000);
})();
