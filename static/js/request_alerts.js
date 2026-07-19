(() => {
  const SOUND_STORAGE_KEY = "emporioAssistantSoundEnabled";
  const ANNOUNCED_STORAGE_KEY = "emporioRequestAlertsAnnounced";
  const MAX_ANNOUNCED_IDS = 100;

  const getCookie = (name) => {
    const prefix = `${name}=`;
    const cookie = document.cookie
      .split(";")
      .map((item) => item.trim())
      .find((item) => item.startsWith(prefix));
    return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : "";
  };

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
      // O alerta visual continua ativo mesmo sem armazenamento local.
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
    const values = Array.from(ids).slice(-MAX_ANNOUNCED_IDS);
    storageSet(ANNOUNCED_STORAGE_KEY, JSON.stringify(values));
  };

  const playAlertSound = async () => {
    if (storageGet(SOUND_STORAGE_KEY) !== "1") {
      return;
    }
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) {
        return;
      }
      const context = new AudioContext();
      if (context.state === "suspended") {
        await context.resume();
      }
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(820, context.currentTime);
      gain.gain.setValueAtTime(0.0001, context.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.18, context.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.32);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start();
      oscillator.stop(context.currentTime + 0.34);
      window.setTimeout(() => context.close(), 600);
    } catch (error) {
      // Navegadores podem bloquear áudio sem interação; o toast e o badge permanecem.
    }
  };

  const ensureBadge = (toolbar) => {
    let badge = document.getElementById("assistant-new-request-badge");
    if (badge || !toolbar) {
      return badge;
    }
    badge = document.createElement("a");
    badge.id = "assistant-new-request-badge";
    badge.className = "assistant-alert-badge assistant-request-alert-badge";
    badge.hidden = true;
    badge.innerHTML = [
      '<span class="assistant-alert-badge-dot" aria-hidden="true"></span>',
      '<strong id="assistant-new-request-badge-count">0</strong>',
      '<span id="assistant-new-request-badge-label">solicitações pendentes</span>',
    ].join("");
    toolbar.prepend(badge);
    return badge;
  };

  const ensureToast = () => {
    let toast = document.getElementById("assistant-request-live-alert");
    if (toast) {
      return toast;
    }
    toast = document.createElement("section");
    toast.id = "assistant-request-live-alert";
    toast.className = "assistant-live-alert assistant-request-live-alert";
    toast.setAttribute("role", "alert");
    toast.setAttribute("aria-live", "assertive");
    toast.setAttribute("aria-atomic", "true");
    toast.hidden = true;

    const header = document.createElement("div");
    header.className = "assistant-live-alert-header";
    const tag = document.createElement("span");
    tag.className = "severity-tag";
    tag.textContent = "Nova solicitação recebida";
    const reference = document.createElement("span");
    reference.id = "assistant-request-alert-reference";
    reference.className = "status-tag";
    header.append(tag, reference);

    const title = document.createElement("h2");
    title.id = "assistant-request-alert-title";
    title.textContent = "Nova solicitação";
    const company = document.createElement("p");
    company.id = "assistant-request-alert-company";
    company.className = "assistant-live-alert-company";
    const delivery = document.createElement("p");
    delivery.id = "assistant-request-alert-delivery";
    delivery.className = "assistant-live-alert-delivery";
    const summary = document.createElement("p");
    summary.id = "assistant-request-alert-summary";

    const actions = document.createElement("div");
    actions.className = "assistant-live-alert-actions";
    const open = document.createElement("a");
    open.id = "assistant-request-alert-open";
    open.className = "button compact";
    open.textContent = "Abrir solicitação";
    const viewed = document.createElement("button");
    viewed.id = "assistant-request-alert-view";
    viewed.className = "button compact secondary request-notification-view-button";
    viewed.type = "button";
    viewed.textContent = "Marcar como visto";
    actions.append(open, viewed);

    toast.append(header, title, company, delivery, summary, actions);
    document.body.append(toast);
    return toast;
  };

  const collectNotifications = (container) => Array.from(
    container.querySelectorAll("[data-request-notification-id]")
  ).map((node) => ({
    id: node.dataset.requestNotificationId || "",
    requestUrl: node.dataset.requestUrl || "#",
    viewUrl: node.dataset.viewUrl || "",
    reference: node.dataset.reference || "",
    company: node.dataset.company || "",
    delivery: node.dataset.delivery || "",
    title: node.dataset.title || "Nova solicitação",
    summary: node.dataset.summary || "Solicitação aguardando conferência.",
  })).filter((notification) => notification.id);

  const hideToast = (toast) => {
    toast.classList.remove("is-visible");
    toast.hidden = true;
    toast.dataset.notificationId = "";
  };

  const showToast = (toast, notification, withSound) => {
    toast.dataset.notificationId = notification.id;
    toast.querySelector("#assistant-request-alert-reference").textContent = notification.reference;
    toast.querySelector("#assistant-request-alert-title").textContent = notification.title;
    toast.querySelector("#assistant-request-alert-company").textContent = notification.company;
    toast.querySelector("#assistant-request-alert-delivery").textContent = notification.delivery;
    toast.querySelector("#assistant-request-alert-summary").textContent = notification.summary;
    const open = toast.querySelector("#assistant-request-alert-open");
    const viewed = toast.querySelector("#assistant-request-alert-view");
    open.href = notification.requestUrl;
    viewed.dataset.notificationId = notification.id;
    viewed.dataset.viewUrl = notification.viewUrl;
    viewed.disabled = false;
    viewed.textContent = "Marcar como visto";
    toast.hidden = false;
    window.requestAnimationFrame(() => toast.classList.add("is-visible"));
    if (withSound) {
      playAlertSound();
    }
  };

  const refreshPanel = async (container) => {
    const refreshUrl = container.dataset.refreshUrl;
    if (!refreshUrl) {
      return false;
    }
    try {
      const response = await fetch(refreshUrl, {
        credentials: "same-origin",
        cache: "no-store",
        headers: {"X-Requested-With": "XMLHttpRequest"},
      });
      if (!response.ok) {
        return false;
      }
      container.innerHTML = await response.text();
      return true;
    } catch (error) {
      return false;
    }
  };

  const initialize = () => {
    const container = document.getElementById("operational-assistant-container");
    if (!container) {
      return;
    }
    const toolbar = document.querySelector(".assistant-alert-toolbar");
    const badge = ensureBadge(toolbar);
    const toast = ensureToast();
    let syncing = false;

    const synchronize = () => {
      if (syncing) {
        return;
      }
      syncing = true;
      try {
        const panel = container.querySelector(".operational-assistant");
        const notifications = collectNotifications(container);
        const count = Number(panel?.dataset.activeRequestCount || notifications.length);
        if (badge) {
          const countNode = badge.querySelector("#assistant-new-request-badge-count");
          const labelNode = badge.querySelector("#assistant-new-request-badge-label");
          countNode.textContent = String(count);
          labelNode.textContent = count === 1
            ? "solicitação pendente"
            : "solicitações pendentes";
          badge.href = panel?.dataset.requestQueueUrl || "#operational-assistant-container";
          badge.hidden = count === 0;
          badge.classList.toggle("has-alert", count > 0);
        }

        const currentIds = new Set(notifications.map((item) => item.id));
        const activeId = toast.dataset.notificationId || "";
        if (activeId && !currentIds.has(activeId)) {
          hideToast(toast);
        }

        if (!notifications.length) {
          hideToast(toast);
          return;
        }

        const announced = readAnnouncedIds();
        const unannounced = notifications.filter((item) => !announced.has(item.id));
        if (unannounced.length) {
          unannounced.forEach((item) => announced.add(item.id));
          saveAnnouncedIds(announced);
          showToast(toast, unannounced[0], true);
          return;
        }

        if (!toast.dataset.notificationId) {
          showToast(toast, notifications[0], false);
        }
      } finally {
        syncing = false;
      }
    };

    const observer = new MutationObserver(synchronize);
    observer.observe(container, {childList: true, subtree: true});

    document.addEventListener("click", async (event) => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const button = event.target.closest(".request-notification-view-button");
      if (!button || !button.dataset.viewUrl) {
        return;
      }
      event.preventDefault();
      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = "Registrando...";
      try {
        const response = await fetch(button.dataset.viewUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "X-CSRFToken": getCookie("csrftoken"),
            "X-Requested-With": "XMLHttpRequest",
          },
        });
        if (response.ok) {
          hideToast(toast);
          await refreshPanel(container);
          synchronize();
          return;
        }
      } catch (error) {
        // Nenhuma decisão ou mudança de status foi executada.
      }
      button.disabled = false;
      button.textContent = originalLabel || "Marcar como visto";
    });

    synchronize();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, {once: true});
  } else {
    initialize();
  }
})();
