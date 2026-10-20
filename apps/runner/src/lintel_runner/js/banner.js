// The Local Runner's banner inside its own browser window. It explains what Lintel is doing and
// hands control back to the person. It never sits over the site's Submit button.
(() => {
  if (window.__lintelBanner) return;
  const host = document.createElement("div");
  host.id = "lintel-runner-banner";
  host.setAttribute("data-lintel", "1");
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `
    <style>
      :host{all:initial}
      .bar{position:fixed;left:16px;right:16px;bottom:16px;z-index:2147483647;font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
           color:#f4f2ec;background:#1c1b18;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.35);padding:12px 14px;display:flex;gap:12px;align-items:flex-start;max-width:720px;margin:0 auto}
      .dot{width:10px;height:10px;border-radius:50%;background:#7aa7ff;margin-top:6px;flex:none}
      .ok .dot{background:#5ccf95}.warn .dot{background:#f2b84b}.bad .dot{background:#ff7a6b}
      .t{font-weight:650}.d{opacity:.85;margin-top:2px}
      ul{margin:6px 0 0;padding-left:18px;opacity:.9}
      li{margin:2px 0}
      .actions{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
      button{font:inherit;font-weight:600;border:0;border-radius:8px;padding:7px 12px;cursor:pointer;background:#f4f2ec;color:#1c1b18}
      button.ghost{background:transparent;color:#f4f2ec;border:1px solid rgba(255,255,255,.3)}
      .brand{font-size:11px;letter-spacing:.08em;text-transform:uppercase;opacity:.6}
      .grow{flex:1}
    </style>
    <div class="bar" id="bar"><span class="dot"></span><div class="grow"><div class="brand">Lintel Local Runner</div>
    <div class="t" id="t"></div><div class="d" id="d"></div><div id="x"></div><div class="actions" id="a"></div></div></div>`;
  const $ = (id) => root.getElementById(id);
  function render(cls, title, desc, extra, actions) {
    $("bar").className = "bar " + (cls || "");
    $("t").textContent = title;
    $("d").textContent = desc || "";
    $("x").innerHTML = "";
    if (extra) $("x").appendChild(extra);
    $("a").innerHTML = "";
    for (const [label, fn, ghost] of actions || []) {
      const b = document.createElement("button");
      b.textContent = label;
      if (ghost) b.className = "ghost";
      b.onclick = fn;
      $("a").appendChild(b);
    }
    if (!host.isConnected) document.documentElement.appendChild(host);
  }
  function list(items) {
    const ul = document.createElement("ul");
    for (const i of items) { const li = document.createElement("li"); li.textContent = i; ul.appendChild(li); }
    return ul;
  }
  window.__lintelBanner = {
    filling: (n) => render("", "Filling the form in your browser", `Typing ${n} value(s) from the payload Lintel prepared. Values are read back after every step.`),
    filled: () => render("ok", "Form filled. Review it in Lintel", "Every value was read back from the page. Approve the exact payload in Lintel, then click the site's own Submit here."),
    armed: (mode) => render("ok", mode === "approved_submission" ? "Approved. Lintel will click Submit once" : "Submit Guard is on",
      mode === "approved_submission" ? "Your approval covers this exact payload." : "Click the site's Submit button when you're ready. Lintel checks the form against your approval first."),
    checking: () => render("", "Checking the form against your approval…", "Reading every field, checkbox and file."),
    passed: () => render("ok", "Matches your approval. Sending…", "The submit intent was recorded before the click."),
    blocked: (v) => {
      const items = [...(v.reasons || [])];
      for (const d of v.diffs || []) items.push(`${d.label}: approved “${String(d.approved ?? "").slice(0, 60)}”, form has “${String(d.live ?? "").slice(0, 60)}”`);
      if (v.unapproved) {
        render("warn", "Not approved yet", "Approve the exact payload in Lintel first. You can still send it yourself; Lintel will record that you did.",
          null, [["Send it myself anyway", () => window.__lintelSendAnyway && window.__lintelSendAnyway(), true]]);
        return;
      }
      render("bad", "Blocked: the form doesn't match your approval", "Nothing was sent.", list(items.slice(0, 8)), v.diffs && v.diffs.length ? [
        ["Send my edits to Lintel to re-approve", () => window.lintelGuardAdopt && window.lintelGuardAdopt()],
        ["Put back the approved values", () => window.lintelGuardRestore && window.lintelGuardRestore(), true],
      ] : []);
    },
    paused: (title, desc) => render("warn", title || "Complete this step, then press Resume", desc || "", null, [["Resume", () => window.lintelResume && window.lintelResume()]]),
    done: (ref) => render("ok", "Application sent", ref ? `Reference ${ref}. Lintel recorded the outcome.` : "Lintel recorded the outcome."),
    uncertain: () => render("warn", "Lintel can't confirm this was sent", "No confirmation appeared. Lintel will not retry. Check your email or the site."),
    info: (title, desc) => render("", title, desc),
    hide: () => host.remove(),
  };
})();
