// Lintel Submit Guard. A seatbelt, not a lock.
//
// Stands in front of the site's own Submit. It listens in the capture phase for the form's submit
// event, the final button click and the Enter key. Before the event proceeds it asks the Local
// Runner (window.lintelGuardCheck, a Playwright binding) to read every field value, checkbox state
// and uploaded file hash and compare them with the approved payload. On a match the runner records
// the submit intent and the click goes through. On a mismatch the click is blocked and a banner
// lists the differing fields.
(() => {
  if (window.__lintelGuardInstalled) return;
  window.__lintelGuardInstalled = true;
  window.__lintelBypass = false;
  let busy = false;

  const formEl = () => document.querySelector("form#application-form") || [...document.forms].sort((a, b) => b.elements.length - a.elements.length)[0];
  const isFinal = (el) => {
    const b = el && el.closest && el.closest("button,input[type=submit]");
    if (!b) return null;
    const t = (b.type || "").toLowerCase();
    return t === "submit" ? b : null;
  };

  async function fileHashes() {
    const out = {};
    for (const input of document.querySelectorAll("input[type=file]")) {
      if (input.files && input.files[0]) {
        const buf = await input.files[0].arrayBuffer();
        const digest = await crypto.subtle.digest("SHA-256", buf);
        out[input.id ? "#" + input.id : input.name] = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
      }
    }
    return out;
  }
  window.__lintelFileHashes = fileHashes;

  async function intercept(ev, submitter, trigger) {
    if (window.__lintelBypass) return;
    window.__lintelLastSubmitter = submitter || null;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    if (busy) return;
    const form = formEl();
    if (form && !form.checkValidity()) {
      // Let the site's own validation speak first; nothing is recorded for an invalid form.
      form.reportValidity();
      return;
    }
    busy = true;
    window.__lintelBanner && window.__lintelBanner.checking();
    let verdict;
    try {
      // Read every field, checkbox and file here, in the page; the runner compares in Python.
      const snapshot = window.__lintelReadForm ? window.__lintelReadForm() : null;
      const files = await fileHashes();
      verdict = await window.lintelGuardCheck({ trigger, snapshot, files });
    } catch (e) {
      verdict = { ok: false, reasons: ["The Local Runner didn't answer. Nothing was sent."] };
    }
    busy = false;
    if (verdict && verdict.ok) {
      window.__lintelBanner && window.__lintelBanner.passed();
      window.__lintelBypass = true;
      if (submitter) submitter.click();
      else if (form) form.requestSubmit();
    } else {
      window.__lintelBanner && window.__lintelBanner.blocked(verdict || { reasons: ["Blocked."] });
    }
  }

  window.__lintelSendAnyway = async () => {
    const ok = window.lintelSubmitAnyway ? await window.lintelSubmitAnyway() : false;
    if (!ok) return;
    window.__lintelBypass = true;
    const s = window.__lintelLastSubmitter;
    if (s) s.click(); else { const f = formEl(); f && f.requestSubmit(); }
  };

  document.addEventListener("click", (ev) => {
    const b = isFinal(ev.target);
    if (b) intercept(ev, b, "click");
  }, true);
  document.addEventListener("submit", (ev) => intercept(ev, ev.submitter || null, "submit"), true);
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" || window.__lintelBypass) return;
    const t = ev.target;
    if (!t || t.tagName === "TEXTAREA" || !t.form) return;
    const submitter = t.form.querySelector("button[type=submit],input[type=submit]");
    intercept(ev, submitter, "enter");
  }, true);
})();
