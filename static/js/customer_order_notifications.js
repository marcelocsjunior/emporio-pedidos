(() => {
  const container = document.getElementById("portal-order-notifications");
  if (!container) {
    return;
  }

  const refreshUrl = container.dataset.refreshUrl;
  const seconds = Number(container.dataset.refreshSeconds || "15");
  if (!refreshUrl || !Number.isFinite(seconds) || seconds < 10) {
    return;
  }

  const refresh = async () => {
    try {
      const response = await fetch(refreshUrl, {
        credentials: "same-origin",
        cache: "no-store",
        headers: {"X-Requested-With": "XMLHttpRequest"},
      });
      if (response.ok) {
        container.innerHTML = await response.text();
      }
    } catch (error) {
      // A notificação renderizada permanece disponível se o polling falhar.
    }
  };

  window.setInterval(refresh, seconds * 1000);
})();
