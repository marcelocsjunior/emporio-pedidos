(() => {
  "use strict";

  const feedback = document.getElementById("copy-feedback");

  const setFeedback = (message) => {
    if (feedback) {
      feedback.textContent = message;
    }
  };

  const fallbackCopy = (element) => {
    element.focus();
    element.select();
    element.setSelectionRange(0, element.value.length);
    return document.execCommand("copy");
  };

  document.querySelectorAll("[data-copy-target]").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) {
        setFeedback("Não foi possível localizar a mensagem.");
        return;
      }

      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(target.value);
        } else if (!fallbackCopy(target)) {
          throw new Error("copy-failed");
        }
        setFeedback("Mensagem copiada. Revise antes de enviar.");
      } catch (_error) {
        setFeedback("Não foi possível copiar automaticamente. Selecione o texto manualmente.");
      }
    });
  });

  document.querySelectorAll("[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) {
        event.preventDefault();
      }
    });
  });
})();
