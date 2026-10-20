// Lintel Lab behaviours: conditional fields, multi-step flow, an unexpected modal and session expiry.
(function () {
  const form = document.getElementById("application-form");

  document.querySelectorAll("[data-close-modal]").forEach((b) =>
    b.addEventListener("click", () => document.getElementById("lab-modal")?.remove())
  );

  if (!form) return;

  // Conditional fields: show a field only when another field has a given value.
  const conditionals = [...form.querySelectorAll("[data-show-if]")];
  function refreshConditionals() {
    for (const el of conditionals) {
      const [name, value] = el.dataset.showIf.split("=");
      const ctrl = form.querySelector(`[name="${CSS.escape(name)}"]:checked`) || form.querySelector(`[name="${CSS.escape(name)}"]:not([type=radio])`);
      const show = ctrl && ctrl.value === value;
      el.hidden = !show;
      el.querySelectorAll("input,select,textarea").forEach((i) => (i.disabled = !show));
    }
  }
  form.addEventListener("change", refreshConditionals);
  refreshConditionals();

  // Multi-step flow.
  const steps = Number(form.dataset.steps || 1);
  if (steps > 1) {
    let current = 0;
    const next = form.querySelector("[data-next]");
    const prev = form.querySelector("[data-prev]");
    const submit = form.querySelector("[data-submit]");
    function show(i) {
      current = i;
      form.querySelectorAll(".field").forEach((f) => (f.hidden = Number(f.dataset.step) !== i));
      form.querySelectorAll("[data-step-tab]").forEach((t) => t.classList.toggle("active", Number(t.dataset.stepTab) === i));
      prev.hidden = i === 0;
      next.hidden = i === steps - 1;
      submit.hidden = i !== steps - 1;
      refreshConditionals();
    }
    next.addEventListener("click", () => {
      const fields = [...form.querySelectorAll(`.field[data-step="${current}"] input, .field[data-step="${current}"] select, .field[data-step="${current}"] textarea`)];
      for (const f of fields) {
        if (!f.checkValidity()) { f.reportValidity(); return; }
      }
      show(current + 1);
    });
    prev.addEventListener("click", () => show(current - 1));
    show(0);
  }

  // Session expiry: the form times out and must be reloaded.
  const expires = Number(form.dataset.sessionExpires || 0);
  if (expires > 0) {
    setTimeout(() => {
      form.hidden = true;
      document.getElementById("session-expired").hidden = false;
    }, expires * 1000);
  }
})();
