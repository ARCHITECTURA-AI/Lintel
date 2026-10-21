// Lintel form reader. Builds a typed description of every form control from the DOM and ARIA
// attributes: label (accessible name), role, type, options, required, limits, visibility,
// section and current value. It reads; it never writes. Page prose is not collected.
(() => {
  const CAPTCHA_SEL = "iframe[src*='recaptcha'],iframe[src*='hcaptcha'],iframe[src*='turnstile'],iframe[src*='challenges.cloudflare'],.g-recaptcha,.h-captcha,.cf-turnstile,[data-lab-captcha]";
  const text = (el) => (el ? (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim() : "");
  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    if (el.closest("[hidden],[aria-hidden='true']")) return false;
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    if (el.type === "file" || el.type === "checkbox" || el.type === "radio") {
      // custom-styled inputs are often visually hidden; judge by their label instead
      const lab = el.labels && el.labels[0];
      if (lab) return visibleBox(lab) || visibleBox(el);
    }
    return visibleBox(el);
  };
  const visibleBox = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden") return false;
    if (el.closest("[hidden],[aria-hidden='true']")) return false;
    return r.width > 1 && r.height > 1 && Number(s.fontSize.replace("px", "")) > 2;
  };
  const byId = (id) => (id ? document.getElementById(id) : null);
  function accName(el) {
    const lb = el.getAttribute("aria-labelledby");
    if (lb) return lb.split(/\s+/).map((i) => text(byId(i))).join(" ").trim();
    const al = el.getAttribute("aria-label");
    if (al) return al.trim();
    if (el.labels && el.labels.length) return [...el.labels].map(text).join(" ").trim();
    const wrap = el.closest("label");
    if (wrap) return text(wrap);
    if (el.placeholder) return el.placeholder.trim();
    if (el.title) return el.title.trim();
    return (el.name || "").trim();
  }
  function section(el) {
    let fs = el.parentElement && el.parentElement.closest("fieldset");
    while (fs && fs.getAttribute("role") === "radiogroup") fs = fs.parentElement && fs.parentElement.closest("fieldset");
    if (!fs) return "";
    const lg = fs.querySelector(":scope > legend");
    return text(lg);
  }
  function locator(el, extra) {
    if (el.id) return { css: "#" + CSS.escape(el.id) };
    const base = `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
    return { css: extra ? base + extra : base };
  }
  const form = document.querySelector("form#application-form") || [...document.forms].sort((a, b) => b.elements.length - a.elements.length)[0] || document.body;
  const controls = [...form.querySelectorAll("input,select,textarea")].filter((el) =>
    !["hidden", "submit", "button", "image", "reset", "search"].includes((el.type || "").toLowerCase()) && !el.closest(CAPTCHA_SEL)
  );
  const fields = [];
  const seenGroups = new Set();
  for (const el of controls) {
    const tag = el.tagName.toLowerCase();
    const type = (el.type || "").toLowerCase();
    let f = null;
    if (type === "radio") {
      if (seenGroups.has(el.name)) continue;
      seenGroups.add(el.name);
      const group = [...form.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)];
      const rg = el.closest("[role=radiogroup]");
      const label = rg ? accName(rg) : (el.closest("fieldset") ? text(el.closest("fieldset").querySelector("legend")) : el.name);
      const checked = group.find((g) => g.checked);
      f = { type: "radio", label, required: group.some((g) => g.required) || (rg && rg.getAttribute("aria-required") === "true"),
            options: group.map((g) => ({ label: text(g.closest("label")) || accName(g), value: g.value })),
            visible: group.some(visible), value: checked ? checked.value : null, locator: { css: `input[type=radio][name="${CSS.escape(el.name)}"]` },
            section: rg ? section(rg) : section(el) };
    } else if (type === "checkbox") {
      const same = form.querySelectorAll(`input[type=checkbox][name="${CSS.escape(el.name)}"]`);
      if (same.length > 1) {
        if (seenGroups.has(el.name)) continue;
        seenGroups.add(el.name);
        const items = [...same];
        const rg = el.closest("[role=group]");
        f = { type: "multiselect", label: rg ? accName(rg) : el.name, required: false, visible: items.some(visible),
              options: items.map((g) => ({ label: accName(g), value: g.value })), value: items.filter((g) => g.checked).map((g) => g.value),
              locator: { css: `input[type=checkbox][name="${CSS.escape(el.name)}"]` }, section: section(el) };
      } else {
        f = { type: "checkbox", label: accName(el), required: el.required, visible: visible(el), value: el.checked, options: [],
              locator: locator(el), section: section(el) };
      }
    } else if (tag === "select") {
      f = { type: el.multiple ? "multiselect" : "select", label: accName(el), required: el.required, visible: visible(el),
            options: [...el.options].filter((o) => o.value !== "").map((o) => ({ label: o.text.trim(), value: o.value })),
            value: el.multiple ? [...el.selectedOptions].map((o) => o.value) : el.value, locator: locator(el), section: section(el) };
    } else if (tag === "textarea") {
      f = { type: "textarea", label: accName(el), required: el.required, visible: visible(el), value: el.value, options: [],
            max_length: el.maxLength > 0 ? el.maxLength : null, locator: locator(el), section: section(el) };
    } else if (type === "file") {
      f = { type: "file", label: accName(el), required: el.required, visible: visible(el), options: [], accept: el.accept || null,
            value: el.files && el.files.length ? el.files[0].name : null, locator: locator(el), section: section(el) };
    } else {
      const t = ["email", "tel", "url", "number", "date"].includes(type) ? type : "text";
      f = { type: t, label: accName(el), required: el.required, visible: visible(el), value: el.value, options: [],
            max_length: el.maxLength > 0 ? el.maxLength : null, locator: locator(el), section: section(el),
            invalid: el.getAttribute("aria-invalid") === "true" || (el.value !== "" && !el.checkValidity()) };
    }
    if (!f.required && el.getAttribute("aria-required") === "true") f.required = true;
    f.label = f.label.replace(/\s*\*\s*$/, "").trim();
    fields.push(f);
  }
  const submit = [...form.querySelectorAll("button,input[type=submit]")].find((b) =>
    visible(b) && ((b.type || "").toLowerCase() === "submit") && !b.hidden);
  const next = [...form.querySelectorAll("button")].find((b) => visible(b) && b.type === "button" && /^(next|continue)\b/i.test(text(b)));
  const dialog = [...document.querySelectorAll("[role=dialog][aria-modal=true],[role=alertdialog]")].find(visible);
  const captcha = [...document.querySelectorAll(CAPTCHA_SEL)].some((e) => e.isConnected);
  const password = [...document.querySelectorAll("input[type=password]")].some(visible);
  const bodyText = (document.body.innerText || "").slice(0, 20000);
  return {
    url: location.href,
    host: location.host,
    fields,
    has_submit: !!submit,
    has_next: !!next,
    dialog: dialog ? text(dialog).slice(0, 200) : null,
    captcha,
    login_wall: password,
    session_expired: /session (has )?expired|timed out/i.test(bodyText) && !!document.querySelector("[role=alert]:not([hidden])"),
    validation_errors: [...document.querySelectorAll("[role=alert]:not([hidden]) , .error")].filter(visible).map(text).slice(0, 5),
  };
})()
