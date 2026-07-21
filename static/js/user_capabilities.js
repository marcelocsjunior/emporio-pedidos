(() => {
  const form = document.querySelector("[data-capability-form]");
  const defaultsNode = document.getElementById("role-capability-defaults");
  if (!form || !defaultsNode) return;
  const defaults = JSON.parse(defaultsNode.textContent);
  const role = form.querySelector("[name=role]");
  const restore = form.querySelector("[name=restore_profile_defaults]");
  const boxes = [...form.querySelectorAll("[name=capabilities]")];

  function profileDefaults() { return new Set(defaults[role.value] || []); }
  function refreshLabels() {
    const base = profileDefaults();
    boxes.forEach((box) => {
      const label = form.querySelector(`[data-capability-state="${box.value}"]`);
      if (!label) return;
      if (base.has(box.value)) label.textContent = box.checked ? "Padrão do perfil" : "Removida individualmente";
      else label.textContent = box.checked ? "Adicionada individualmente" : "Não incluída";
    });
  }
  function applyDefaults() {
    const base = profileDefaults();
    boxes.forEach((box) => { box.checked = base.has(box.value); });
    restore.value = "1";
    refreshLabels();
  }
  role.addEventListener("change", applyDefaults);
  boxes.forEach((box) => box.addEventListener("change", () => { restore.value = ""; refreshLabels(); }));
  form.querySelector("[data-restore-capabilities]").addEventListener("click", applyDefaults);
  refreshLabels();
})();
