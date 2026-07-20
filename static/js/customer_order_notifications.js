(() => {
  const SOUND_STORAGE_KEY = "emporioCustomerOrderNotificationsSoundEnabled";
  const ANNOUNCED_STORAGE_KEY = "emporioCustomerOrderNotificationsAnnounced";
  const MAX_ANNOUNCED_IDS = 100;
  const TOAST_VISIBLE_MS = 12000;
  const container = document.getElementById("portal-order-notifications");
  if (!container) {
    return;
  }

  const refreshUrl = container.dataset.refreshUrl;
  const seconds = Number(container.dataset.refreshSeconds || "15");
  if (!refreshUrl || !Number.isFinite(seconds) || seconds < 10) {
    return;
  }

  const storageGet = (key) => {
    try {
      return window.localStorage.getItem(key);
    } catch (error) {
      return null;
    }
  };

  const storageSet = (key, value) => {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      // O alerta visual continua disponível sem armazenamento local.
    }
  };

  const readAnnouncedIds = () => {
    try {
      const parsed = JSON.parse(storageGet(ANNOUNCED_STORAGE_KEY) || "[]");
      return new Set(Array.isArray(parsed) ? parsed.filter(Boolean) : []);
    } catch (error) {
      return new Set();
    }
  };

  const saveAnnouncedIds = (ids) => {
    storageSet(
      ANNOUNCED_STORAGE_KEY,
      JSON.stringify(Array.from(ids).slice(-MAX_ANNOUNCED_IDS)),
    );
  };

  const getCookie = (name) => {
    const prefix = `${name}=`;
    const cookie = document.cookie
      .split(";")
      .map((item) => item.trim())
      .find((item) => item.startsWith(prefix));
    return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : "";
  };

  const collectNotifications = () => Array.from(
    container.querySelectorAll("[data-order-notification-id]"),
  ).map((node) => ({
    id: node.dataset.orderNotificationId || "",
    orderNumber: node.dataset.orderNumber || "",
    newStatus: node.dataset.newStatus || "",
    message: node.dataset.message || "Seu pedido teve uma atualização.",
    orderUrl: node.dataset.orderUrl || "#",
    viewedUrl: node.dataset.viewedUrl || "",
  })).filter((notification) => notification.id);

  let soundEnabled = storageGet(SOUND_STORAGE_KEY) === "1";
  let audioContext = null;
  let toastTimer = null;
  let refreshing = false;
  const sessionAnnouncedIds = new Set();

  const updateSoundControls = () => {
    container.querySelectorAll(".portal-order-sound-toggle").forEach((button) => {
      button.setAttribute("aria-pressed", soundEnabled ? "true" : "false");
      button.textContent = soundEnabled ? "Som ligado" : "Ativar som";
      button.title = soundEnabled
        ? "Desativar o som dos alertas de pedidos"
        : "Ativar o som dos alertas de pedidos";
    });
  };

  const playAlertSound = async () => {
    if (!soundEnabled) {
      return;
    }
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) {
        return;
      }
      audioContext = audioContext || new AudioContext();
      if (audioContext.state === "suspended") {
        await audioContext.resume();
      }
      const oscillator = audioContext.createOscillator();
      const gain = audioContext.createGain();
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(780, audioContext.currentTime);
      gain.gain.setValueAtTime(0.0001, audioContext.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.16, audioContext.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + 0.3);
      oscillator.connect(gain);
      gain.connect(audioContext.destination);
      oscillator.start();
      oscillator.stop(audioContext.currentTime + 0.32);
    } catch (error) {
      // Autoplay ou Web Audio podem ser bloqueados; o polling e o toast continuam.
    }
  };

  const ensureToast = () => {
    let toast = document.getElementById("portal-order-live-alert");
    if (toast) {
      return toast;
    }
    toast = document.createElement("section");
    toast.id = "portal-order-live-alert";
    toast.className = "portal-order-live-alert";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    toast.setAttribute("aria-atomic", "true");
    toast.hidden = true;
    toast.innerHTML = [
      '<div class="portal-order-live-alert-header">',
      '<span class="eyebrow">Atualização de pedido</span>',
      '<button class="portal-order-live-alert-close" type="button" aria-label="Fechar aviso">×</button>',
      "</div>",
      '<h2 id="portal-order-live-alert-title">Pedido atualizado</h2>',
      '<p><strong>Novo status:</strong> <span id="portal-order-live-alert-status"></span></p>',
      '<p id="portal-order-live-alert-message"></p>',
      '<div class="portal-order-live-alert-actions">',
      '<a id="portal-order-live-alert-open" class="button compact ghost">Abrir pedido</a>',
      '<button id="portal-order-live-alert-viewed" class="button compact secondary" type="button">Marcar como visto</button>',
      "</div>",
    ].join("");
    document.body.append(toast);
    return toast;
  };

  const toast = ensureToast();

  const hideToast = (notificationId = "") => {
    if (notificationId && toast.dataset.notificationId !== notificationId) {
      return;
    }
    window.clearTimeout(toastTimer);
    toast.classList.remove("is-visible");
    toast.hidden = true;
    toast.dataset.notificationId = "";
  };

  const showToast = (notification) => {
    window.clearTimeout(toastTimer);
    toast.dataset.notificationId = notification.id;
    toast.querySelector("#portal-order-live-alert-title").textContent =
      `Pedido ${notification.orderNumber} atualizado`;
    toast.querySelector("#portal-order-live-alert-status").textContent = notification.newStatus;
    toast.querySelector("#portal-order-live-alert-message").textContent = notification.message;
    toast.querySelector("#portal-order-live-alert-open").href = notification.orderUrl;
    const viewed = toast.querySelector("#portal-order-live-alert-viewed");
    viewed.dataset.notificationId = notification.id;
    viewed.dataset.viewedUrl = notification.viewedUrl;
    viewed.disabled = false;
    viewed.textContent = "Marcar como visto";
    toast.hidden = false;
    window.requestAnimationFrame(() => toast.classList.add("is-visible"));
    toastTimer = window.setTimeout(() => hideToast(notification.id), TOAST_VISIBLE_MS);
    playAlertSound();
  };

  const synchronize = (announceNew) => {
    updateSoundControls();
    const notifications = collectNotifications();
    const currentIds = new Set(notifications.map((item) => item.id));
    if (toast.dataset.notificationId && !currentIds.has(toast.dataset.notificationId)) {
      hideToast();
    }

    const announced = readAnnouncedIds();
    sessionAnnouncedIds.forEach((id) => announced.add(id));
    if (!announceNew) {
      notifications.forEach((item) => {
        announced.add(item.id);
        sessionAnnouncedIds.add(item.id);
      });
      saveAnnouncedIds(announced);
      return;
    }
    const unannounced = notifications.filter((item) => !announced.has(item.id));
    if (!unannounced.length) {
      return;
    }
    announced.add(unannounced[0].id);
    sessionAnnouncedIds.add(unannounced[0].id);
    saveAnnouncedIds(announced);
    showToast(unannounced[0]);
  };

  const refresh = async () => {
    if (refreshing || document.hidden) {
      return;
    }
    refreshing = true;
    try {
      const response = await fetch(refreshUrl, {
        credentials: "same-origin",
        cache: "no-store",
        headers: {"X-Requested-With": "XMLHttpRequest"},
      });
      if (response.ok) {
        container.innerHTML = await response.text();
        synchronize(true);
      }
    } catch (error) {
      // A notificação renderizada permanece disponível se o polling falhar.
    } finally {
      refreshing = false;
    }
  };

  document.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }
    if (event.target.closest(".portal-order-sound-toggle")) {
      soundEnabled = !soundEnabled;
      storageSet(SOUND_STORAGE_KEY, soundEnabled ? "1" : "0");
      updateSoundControls();
      if (soundEnabled) {
        await playAlertSound();
      }
      return;
    }
    if (event.target.closest(".portal-order-live-alert-close")) {
      hideToast();
      return;
    }
    const viewed = event.target.closest("#portal-order-live-alert-viewed");
    if (!viewed || !viewed.dataset.viewedUrl) {
      return;
    }
    viewed.disabled = true;
    viewed.textContent = "Registrando...";
    try {
      const response = await fetch(viewed.dataset.viewedUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": getCookie("csrftoken"),
          "X-Requested-With": "XMLHttpRequest",
        },
      });
      if (response.ok) {
        hideToast(viewed.dataset.notificationId || "");
        await refresh();
        return;
      }
    } catch (error) {
      // A lista persistente permite tentar novamente sem quebrar o polling.
    }
    viewed.disabled = false;
    viewed.textContent = "Marcar como visto";
  });

  synchronize(false);
  window.setInterval(refresh, seconds * 1000);
})();
