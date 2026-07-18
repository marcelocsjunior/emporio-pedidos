(() => {
  const container = document.getElementById("order-items");
  const addButton = document.getElementById("add-item");
  const template = document.getElementById("empty-item-template");
  const totalForms = document.getElementById("id_items-TOTAL_FORMS");

  if (!container || !addButton || !template || !totalForms) return;

  const bindRemove = (row) => {
    const button = row.querySelector("[data-remove-item]");
    const checkbox = row.querySelector('input[name$="-DELETE"]');
    if (!button || !checkbox) return;

    button.addEventListener("click", () => {
      checkbox.checked = true;
      row.classList.add("is-removed");
      row.setAttribute("aria-hidden", "true");
    });
  };

  container.querySelectorAll("[data-item-row]").forEach(bindRemove);

  addButton.addEventListener("click", () => {
    const index = Number.parseInt(totalForms.value, 10);
    if (!Number.isFinite(index) || index >= 50) return;

    const html = template.innerHTML.replaceAll("__prefix__", String(index));
    const fragment = document.createRange().createContextualFragment(html);
    const row = fragment.querySelector("[data-item-row]");
    if (!row) return;

    container.appendChild(fragment);
    totalForms.value = String(index + 1);
    bindRemove(row);
    row.querySelector("select, input")?.focus();
  });
})();
