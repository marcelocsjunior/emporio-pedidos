(() => {
  const form = document.querySelector("[data-capability-form]");
  const defaultsNode = document.getElementById("role-capability-defaults");
  if (!form || !defaultsNode) return;
  const defaults = JSON.parse(defaultsNode.textContent);
  const role = form.querySelector("[name=role]");
  const restore = form.querySelector("[name=restore_profile_defaults]");
  const rows = [...form.querySelectorAll("[data-capability]")];

  function profileDefaults() { return new Set(defaults[role.value] || []); }
  function refresh() {
    const base = profileDefaults();
    rows.forEach((row) => {
      const inherited = base.has(row.dataset.capability);
      const selected = row.querySelector("input:checked");
      const inheritedLabel = row.querySelector("[data-inherited]");
      const effectiveLabel = row.querySelector("[data-effective]");
      if (!selected || !inheritedLabel || !effectiveLabel) return;
      const effective = selected.value === "allow" || (selected.value === "default" && inherited);
      inheritedLabel.textContent = inherited ? "Herdado: permitido" : "Herdado: não permitido";
      effectiveLabel.textContent = effective ? "Efetivo: permitido" : "Efetivo: bloqueado";
      effectiveLabel.classList.toggle("is-allowed", effective);
      effectiveLabel.classList.toggle("is-denied", !effective);
    });
  }
  function applyDefaults() {
    rows.forEach((row) => {
      const defaultRadio = row.querySelector('input[value="default"]');
      if (defaultRadio) defaultRadio.checked = true;
    });
    restore.value = "1";
    refresh();
  }
  role.addEventListener("change", refresh);
  form.addEventListener("change", (event) => {
    if (event.target.matches('[name^="capability_state__"]')) restore.value = "";
    refresh();
  });
  form.querySelector("[data-restore-capabilities]").addEventListener("click", applyDefaults);
  refresh();
})();
