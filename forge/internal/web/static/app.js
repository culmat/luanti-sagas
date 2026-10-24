// Saga Forge web UI: vanilla ES module, no build step, no third-party code. Every change goes
// through the API (internal/web), which runs the sagas and avanti tools.

const token = (() => {
  const m = location.hash.match(/[#&]t=([^&]+)/);
  if (m) {
    sessionStorage.setItem("sagaforge-token", m[1]);
    history.replaceState(null, "", location.pathname + "#/");
  }
  return sessionStorage.getItem("sagaforge-token") || "";
})();

// ---------------------------------------------------------------- helpers
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === undefined || c === null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const $ = (sel) => document.querySelector(sel);
const main = () => $("#main");
function show(...nodes) {
  main().replaceChildren(...nodes.flat().filter((n) => n !== null && n !== undefined && n !== false));
  main().focus({ preventScroll: true });
}
function toast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 4000);
}

async function api(path, body, method) {
  method = method || (body === undefined ? "GET" : "POST");
  const res = await fetch(path, {
    method,
    headers: { "X-Saga-Forge-Token": token, ...(method !== "GET" ? { "Content-Type": "application/json" } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data.error && data.error.message) || res.statusText);
  return data;
}

// ---------------------------------------------------------------- jobs and events
const jobs = new Map(); // id -> job
const waiters = new Map(); // id -> [resolve, reject]
const events = new EventSource(`/api/events?t=${encodeURIComponent(token)}`);
events.addEventListener("job", (ev) => {
  const j = JSON.parse(ev.data);
  jobs.set(j.id, j);
  if (j.id === shownJob) $("#job-title").textContent = `${j.title}${j.state === "running" ? " …" : j.state === "done" ? " ✓" : j.state === "failed" ? " ✗" : ""}`;
  if (["done", "failed", "cancelled"].includes(j.state) && waiters.has(j.id)) {
    const [ok, fail] = waiters.get(j.id);
    waiters.delete(j.id);
    if (j.state === "done") ok(j);
    else fail(Object.assign(new Error(j.error || j.state), { job: j }));
  }
});
events.addEventListener("log", (ev) => {
  const { job, line } = JSON.parse(ev.data);
  if (job === shownJob) {
    const log = $("#job-log");
    log.append(line.msg + "\n");
    log.scrollTop = log.scrollHeight;
  }
});
events.addEventListener("luanti", (ev) => {
  const d = JSON.parse(ev.data);
  state.status.running = d.running ? { game: d.game } : null;
  if (!d.running && d.error) toast(`Luanti stopped: ${d.error}`);
  renderWho();
});
events.addEventListener("signed_in", (ev) => {
  state.status.login = JSON.parse(ev.data).login;
  renderWho();
});

let shownJob = null;
$("#job-close").addEventListener("click", () => { $("#jobs").hidden = true; });

// follow shows a job's log and resolves when it is done (rejects when it failed).
function follow(job) {
  shownJob = job.id;
  $("#jobs").hidden = false;
  $("#job-title").textContent = `${job.title} …`;
  $("#job-log").textContent = (job.log || []).map((l) => l.msg).join("\n");
  const known = jobs.get(job.id);
  if (known && ["done", "failed", "cancelled"].includes(known.state)) {
    return known.state === "done" ? Promise.resolve(known) : Promise.reject(new Error(known.error || known.state));
  }
  return new Promise((ok, fail) => {
    waiters.set(job.id, [ok, fail]);
    // the job may have finished before we subscribed
    api(`/api/jobs/${job.id}`).then((j) => {
      if (waiters.has(j.id) && ["done", "failed", "cancelled"].includes(j.state)) {
        waiters.delete(j.id);
        if (j.state === "done") ok(j);
        else fail(new Error(j.error || j.state));
      }
    }).catch(() => {});
  });
}

// busy disables a button while work runs and reports failures.
async function busy(button, work) {
  const label = button.textContent;
  button.disabled = true;
  button.replaceChildren(h("span", { class: "spinner" }), " ", label);
  try {
    return await work();
  } catch (e) {
    toast(e.message);
    throw e;
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

// ---------------------------------------------------------------- state
const state = { status: {}, catalog: null, vocab: null, drafts: [] };
const LICENCES = [
  ["CC0-1.0", "CC0 (public domain)"],
  ["CC-BY-4.0", "CC BY 4.0 (credit the author)"],
  ["CC-BY-3.0", "CC BY 3.0"],
  ["CC-BY-SA-4.0", "CC BY-SA 4.0 (credit, share alike)"],
  ["CC-BY-SA-3.0", "CC BY-SA 3.0"],
  ["MIT", "MIT"],
];
const SIZES = [
  [8, "Tiny", "a shrine, a well, a statue"],
  [12, "Small", "a hut, a cart, a boulder"],
  [20, "House", "about as big as a house"],
  [32, "Large", "a tower, a temple, a ship"],
  [48, "Huge", "a castle, a big ruin"],
  [72, "Giant", "a fortress, a whole site"],
];
const GAMES = { minetest: "Minetest Game", mineclonia: "Mineclonia", mineclone2: "VoxeLibre" };

async function refreshStatus() {
  state.status = await api("/api/status");
  renderWho();
  return state.status;
}
async function refreshCatalog() {
  state.catalog = await api("/api/catalog");
  return state.catalog;
}
async function refreshDrafts() {
  state.drafts = await api("/api/drafts");
  return state.drafts;
}
async function vocabulary() {
  if (!state.vocab) state.vocab = await api("/api/vocabulary");
  return state.vocab;
}

function renderWho() {
  const s = state.status;
  const parts = [];
  if (s.clone_mode) parts.push(h("span", { class: "badge", title: s.workspace }, "your clone"));
  else if (s.draft) parts.push(h("span", { class: "badge", title: "the draft you are working on" }, `draft: ${s.draft}`));
  if (s.running) parts.push(h("span", { class: "badge" }, "Luanti is running"));
  parts.push(s.login ? h("span", {}, `GitHub: ${s.login}`) : h("a", { href: "#/settings" }, "Sign in to GitHub"));
  $("#who").replaceChildren(...parts);
}

// ---------------------------------------------------------------- routing
const routes = [
  [/^#\/?$/, viewGallery, "gallery"],
  [/^#\/add$/, viewAdd, "add"],
  [/^#\/landmark\/([a-z0-9_]+)\/([a-z0-9_]+)$/, viewLandmark, "gallery"],
  [/^#\/drafts$/, viewDrafts, "drafts"],
  [/^#\/settings$/, viewSettings, "settings"],
];
async function route() {
  if (!state.status.ready) {
    await refreshStatus().catch((e) => show(h("p", { class: "notice warn" }, e.message)));
    if (!state.status.ready) return viewSetup();
  }
  const hash = location.hash || "#/";
  for (const [re, view, tab] of routes) {
    const m = hash.match(re);
    if (m) {
      document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
      try {
        await view(...m.slice(1));
      } catch (e) {
        show(h("h1", {}, "Something went wrong"), h("p", { class: "notice warn" }, e.message));
      }
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", () => {
  // a new start of Saga Forge has a new token: take it and start over
  const m = location.hash.match(/[#&]t=([^&]+)/);
  if (m) {
    sessionStorage.setItem("sagaforge-token", m[1]);
    location.replace(location.pathname + "#/");
    location.reload();
    return;
  }
  route();
});

// ---------------------------------------------------------------- setup
function viewSetup() {
  const s = state.status;
  const go = h("button", { class: "primary", type: "button" }, "Set up");
  go.addEventListener("click", () => busy(go, async () => {
    const job = await api("/api/setup", { update: false });
    await follow(job);
    state.status.ready = false;
    await route();
  }));
  show(
    h("h1", {}, "Welcome to Saga Forge"),
    h("p", { class: "lead" }, "Saga Forge turns 3D models into landmarks for Luanti and sends them to the Sagas project. ",
      "Before the first start it fetches its tools: git (if you don't have it), uv and Python for the model tools, ",
      "and copies of the Sagas and avanti projects. That is about 200 MB once; after that it works offline."),
    s.missing && s.missing.length ? h("p", { class: "muted" }, `Still to do: ${s.missing.join(", ")}.`) : null,
    h("div", { class: "row" }, go),
  );
}

// ---------------------------------------------------------------- gallery
async function viewGallery() {
  show(h("p", { class: "muted" }, h("span", { class: "spinner" }), " Loading landmarks…"));
  const [cat] = await Promise.all([refreshCatalog(), refreshDrafts(), refreshStatus()]);
  const mine = new Map(); // selector -> draft name
  for (const d of state.drafts) for (const sel of d.landmarks) mine.set(sel, d.name);
  const sent = state.status.sent || {};
  const sections = cat.sagas.map((saga) => {
    const items = cat.landmarks.filter((l) => l.saga === saga.id);
    return h("section", {},
      h("h2", {}, saga.title.replace(/^Sagas: /, "")),
      h("p", { class: "muted" }, saga.description),
      h("div", { class: "grid" }, items.map((l) => {
        const draft = mine.get(l.selector);
        return h("a", { class: "card", href: `#/landmark/${l.selector}` },
          l.preview ? h("div", { class: "thumb" }, h("img", { src: `/files/${l.preview}`, alt: "", loading: "lazy" })) : null,
          h("div", { class: "title" }, l.title),
          h("div", { class: "meta" }, `${l.size[0]} × ${l.size[1]} × ${l.size[2]} nodes`),
          draft ? h("span", { class: "badge" }, sent[draft] ? "sent" : "changed by you") : null);
      }), items.length === 0 ? h("p", { class: "muted" }, "No landmarks yet.") : null));
  });
  show(
    h("div", { class: "row" }, h("h1", {}, "Landmarks"), h("a", { class: "button primary", href: "#/add" }, "Add a landmark")),
    h("p", { class: "lead" }, "Every landmark is a 3D model turned into Luanti nodes. Open one to look at it from all sides, try other sizes, change where it appears, or walk around it in the game."),
    sections,
    cat.unbuilt.length ? h("p", { class: "muted small" }, `Not built yet: ${cat.unbuilt.join(", ")}`) : null,
  );
}

// ---------------------------------------------------------------- add a landmark
const wizard = { step: 0, saga: "", newSaga: "", newSagaText: "", url: "", file: null, license: "", author: "", ai: false, title: "", lore: "", hints: "", size: 20 };
const STEPS = ["Saga", "Model", "Name and place", "Size"];

async function viewAdd() {
  if (!state.catalog) await refreshCatalog();
  const steps = h("ol", { class: "steps" }, STEPS.map((s, i) => h("li", { class: i === wizard.step ? "now" : i < wizard.step ? "done" : "" }, `${i + 1}. ${s}`)));
  const back = wizard.step > 0 ? h("button", { type: "button", onclick: () => { wizard.step--; viewAdd(); } }, "Back") : null;
  const body = [stepSaga, stepModel, stepStory, stepSize][wizard.step]();
  show(h("h1", {}, "Add a landmark"), steps, body.content, h("div", { class: "row end" }, back, body.next));
}

function nextButton(label, valid, onNext) {
  const b = h("button", { class: "primary", type: "button" }, label);
  const update = () => { b.disabled = !valid(); };
  b.addEventListener("click", () => onNext(b));
  update();
  return [b, update];
}

function stepSaga() {
  let update;
  const cards = state.catalog.sagas.map((s) => {
    const n = state.catalog.landmarks.filter((l) => l.saga === s.id).length;
    return h("button", { type: "button", class: `card${wizard.saga === s.id ? " selected" : ""}`, onclick: () => { wizard.saga = s.id; viewAdd(); } },
      h("div", { class: "title" }, s.title.replace(/^Sagas: /, "")), h("div", { class: "meta" }, s.description), h("div", { class: "meta" }, `${n} landmark${n === 1 ? "" : "s"}`));
  });
  const fresh = h("button", { type: "button", class: `card${wizard.saga === "" ? " selected" : ""}`, onclick: () => { wizard.saga = ""; viewAdd(); } },
    h("div", { class: "title" }, "A new saga"), h("div", { class: "meta" }, "Start a theme of your own: Vikings, pirates, a fantasy kingdom…"));
  const name = h("input", { type: "text", value: wizard.newSaga, placeholder: "Vikings", oninput: (e) => { wizard.newSaga = e.target.value; update(); } });
  const text = h("input", { type: "text", value: wizard.newSagaText, placeholder: "longhouses and ships of the north", oninput: (e) => { wizard.newSagaText = e.target.value; } });
  let next;
  [next, update] = nextButton("Next", () => wizard.saga !== "" || wizard.newSaga.trim().length >= 3, () => { wizard.step = 1; viewAdd(); });
  return {
    content: h("div", {},
      h("p", { class: "lead" }, "Which theme does your landmark belong to?"),
      h("div", { class: "grid" }, cards, fresh),
      wizard.saga === "" ? h("div", { class: "panel" }, h("label", {}, "Name of the new saga", name), h("label", {}, "In a few words", text)) : null),
    next,
  };
}

function stepModel() {
  let update;
  const input = h("input", { type: "file", accept: ".glb,.gltf,.obj,.stl,.dae,.ply,.vox,.zip", class: "hidden" });
  const drop = h("div", { class: "drop", tabindex: "0", role: "button" },
    wizard.file ? `${wizard.file.name} (${(wizard.file.size / 1048576).toFixed(1)} MB)` : "Drop the model file here, or click to choose it (.glb, .gltf, .obj, .zip …)");
  const pick = (f) => {
    if (!f) return;
    if (f.size > 50 * 1048576) { toast("That file is larger than 50 MB. A .glb download is usually much smaller."); return; }
    wizard.file = f;
    drop.textContent = `${f.name} (${(f.size / 1048576).toFixed(1)} MB)`;
    update();
  };
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") input.click(); });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); pick(e.dataTransfer.files[0]); });
  input.addEventListener("change", () => pick(input.files[0]));
  const url = h("input", { type: "url", value: wizard.url, placeholder: "https://…", oninput: (e) => { wizard.url = e.target.value.trim(); update(); } });
  const lic = h("select", { onchange: (e) => { wizard.license = e.target.value; update(); } },
    h("option", { value: "" }, "Choose the licence shown on the model's page"),
    LICENCES.map(([v, t]) => h("option", { value: v, selected: wizard.license === v }, t)));
  const author = h("input", { type: "text", value: wizard.author, placeholder: "Who made the model", oninput: (e) => { wizard.author = e.target.value; } });
  const ai = h("input", { type: "checkbox", checked: wizard.ai, onchange: (e) => { wizard.ai = e.target.checked; } });
  let next;
  [next, update] = nextButton("Next", () => (wizard.url || wizard.file) && wizard.license, () => { wizard.step = 2; viewAdd(); });
  const site = /sketchfab\.com/.test(wizard.url) ? h("p", { class: "notice" }, "Sketchfab needs a login to download: open the page, choose Download ▸ glTF, and drop the zip below.") : null;
  return {
    content: h("div", { class: "stack" },
      h("p", { class: "lead" }, "Where is the model? Only models with a free licence can become landmarks."),
      h("label", {}, "Link to the model's page", h("span", { class: "hint" }, "Poly Haven and direct links to a model file are downloaded for you. Always add the page: it shows where the model comes from."), url),
      site,
      h("label", {}, "The model file", h("span", { class: "hint" }, "Only needed when the site wants a login (Sketchfab). Saga Forge keeps this original next to the landmark.")),
      drop, input,
      h("label", {}, "Licence", lic),
      h("label", {}, "Author", author),
      h("label", { class: "check" }, ai, "The model was made with an AI tool"),
    ),
    next,
  };
}

function stepStory() {
  let update;
  const title = h("input", { type: "text", value: wizard.title, placeholder: "Old Watchtower", oninput: (e) => { wizard.title = e.target.value; update(); } });
  const lore = h("textarea", { placeholder: "A line players read when they find it", oninput: (e) => { wizard.lore = e.target.value; } }, wizard.lore);
  const suggest = h("div", { class: "chips" });
  const hints = h("textarea", { placeholder: "on sea cliffs in the cold north, rare", oninput: (e) => { wizard.hints = e.target.value; showHints(); } }, wizard.hints);
  let timer;
  function showHints() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (!wizard.hints.trim()) { suggest.replaceChildren(); return; }
      const r = await api(`/api/hints?text=${encodeURIComponent(wizard.hints)}`).catch(() => null);
      if (!r) return;
      const f = r.fields;
      suggest.replaceChildren(
        ...f.site.map((s) => h("span", { class: "badge" }, s.replace("+", " + "))),
        h("span", { class: "badge" }, f.exposure),
        ...f.biomes.map((b) => h("span", { class: "badge" }, b)),
        h("span", { class: "badge" }, `about one in ${f.rarity} areas`));
    }, 300);
  }
  showHints();
  let next;
  [next, update] = nextButton("Next", () => wizard.title.trim().length >= 3, () => { wizard.step = 3; viewAdd(); });
  return {
    content: h("div", { class: "stack" },
      h("label", {}, "Name of the landmark", title),
      h("label", {}, "Where should it appear?", h("span", { class: "hint" }, "In your own words: terrain, climate, how often. You can fine-tune it afterwards."), hints),
      suggest,
      h("label", {}, "A line of lore (optional)", lore)),
    next,
  };
}

function stepSize() {
  const cards = SIZES.map(([n, name, text]) => h("button", { type: "button", class: `card${wizard.size === n ? " selected" : ""}`, onclick: () => { wizard.size = n; viewAdd(); } },
    h("div", { class: "title" }, name), h("div", { class: "meta" }, text), h("div", { class: "meta" }, `about ${n} nodes long`)));
  const [next] = nextButton("Create the landmark", () => true, (b) => busy(b, createLandmark));
  return {
    content: h("div", {}, h("p", { class: "lead" }, "Roughly how big? You will see it next to trees and a player in the next step and can change it freely."), h("div", { class: "grid" }, cards)),
    next,
  };
}

async function createLandmark() {
  let file = "";
  if (wizard.file) {
    const data = await new Promise((ok, fail) => {
      const r = new FileReader();
      r.onload = () => ok(String(r.result).replace(/^data:[^,]*,/, ""));
      r.onerror = () => fail(r.error);
      r.readAsDataURL(wizard.file);
    });
    file = (await api("/api/upload", { name: wizard.file.name, data })).path;
  }
  const req = {
    title: wizard.title.trim(), url: wizard.url, file, license: wizard.license, author: wizard.author.trim(),
    saga: wizard.saga, new_saga: wizard.saga ? "" : `${wizard.newSaga.trim()}: ${wizard.newSagaText.trim()}`,
    size: wizard.size, hints: wizard.hints.trim(), lore: wizard.lore.trim(), ai: wizard.ai,
  };
  const job = await follow(await api("/api/landmarks", req));
  const sum = job.result;
  Object.assign(wizard, { step: 0, url: "", file: null, title: "", lore: "", hints: "" });
  state.catalog = null;
  await refreshStatus();
  toast(`${sum.title} is ready: ${sum.dims.join(" × ")} nodes.`);
  location.hash = `#/landmark/${sum.saga}/${sum.id}`;
}

// ---------------------------------------------------------------- one landmark
let viewerSize = null;
window.addEventListener("message", (ev) => {
  if (ev.origin !== location.origin || !ev.data || ev.data.type !== "sagas-size") return;
  viewerSize = ev.data.size;
  const b = $("#use-size");
  if (b) {
    b.textContent = `Use size ${viewerSize}`;
    b.disabled = false;
  }
});

async function viewLandmark(saga, id) {
  const sel = `${saga}/${id}`;
  show(h("p", { class: "muted" }, h("span", { class: "spinner" }), " Opening…"));
  const [cat, status] = await Promise.all([refreshCatalog(), refreshStatus(), refreshDrafts()]);
  const l = cat.landmarks.find((x) => x.selector === sel);
  if (!l) throw new Error(`${sel} is not built in this workspace (it may live in another draft).`);
  const draft = state.drafts.find((d) => d.current);
  const editable = status.clone_mode || (draft && draft.landmarks.includes(sel)) || status.draft === sel.replace("/", "-");
  const head = h("div", {},
    h("p", { class: "muted small" }, h("a", { href: "#/" }, "Landmarks"), " / ", saga),
    h("h1", {}, l.title),
    h("p", { class: "muted" }, `${l.size[0]} × ${l.size[1]} × ${l.size[2]} nodes · ${l.license} · by ${l.author || "unknown"}`,
      l.source_url ? [" · ", h("a", { href: l.source_url, target: "_blank", rel: "noopener" }, "original")] : null,
      l.edited ? [" · ", h("span", { class: "badge" }, "edited model")] : null));
  const frame = h("iframe", { class: "viewer", title: `${l.title} in 3D` });
  const panels = h("div", {});
  show(head, editable ? null : startEditing(sel), h("div", { class: "split" }, h("div", {}, frame, h("p", { class: "muted small" }, "Drag to turn, scroll to zoom. Change the size with − and + in the viewer, then use it here.")), panels));
  api("/api/view", { selector: sel }).then((r) => { frame.src = r.path; }).catch((e) => { frame.replaceWith(h("p", { class: "notice warn" }, e.message)); });
  panels.append(
    sizePanel(sel, l, editable, frame),
    later(vocabulary().then((vocab) => placementPanel(sel, l, vocab, editable))),
    storyPanel(sel, l, editable),
    later(checkPanel(sel, editable, frame)),
    later(tourPanel(sel)),
    submitPanel(status, draft, editable));
}

// later shows a placeholder until a panel that needs the tools is ready.
function later(promise) {
  const box = h("div", { class: "panel" }, h("span", { class: "spinner" }));
  promise.then((panel) => box.replaceWith(panel), (e) => box.replaceChildren(h("p", { class: "notice warn" }, e.message)));
  return box;
}

function startEditing(sel) {
  const b = h("button", { class: "primary", type: "button" }, "Change this landmark");
  b.addEventListener("click", () => busy(b, async () => {
    await api("/api/landmarks/edit", { selector: sel });
    await viewLandmark(...sel.split("/"));
  }));
  return h("div", { class: "notice row" }, h("span", {}, "You are looking at the landmark as it is in the game. To change it, start a draft:"), b);
}

function sizePanel(sel, l, editable, frame) {
  const n = h("input", { type: "number", min: "4", max: "400", value: l.target_size, disabled: !editable });
  const apply = h("button", { type: "button", disabled: !editable }, "Apply");
  const use = h("button", { type: "button", id: "use-size", disabled: true }, "Use the viewer's size");
  const set = async (size) => {
    const job = await follow(await api("/api/landmarks/command", { selector: sel, lines: [`/size ${size}`] }));
    toast(`Now ${job.result.size.join(" × ")} nodes.`);
    frame.src = frame.src;
  };
  apply.addEventListener("click", () => busy(apply, () => set(+n.value)));
  use.addEventListener("click", () => { if (viewerSize) { n.value = viewerSize; busy(use, () => set(viewerSize)); } });
  if (!editable) use.classList.add("hidden");
  return h("div", { class: "panel" }, h("h3", {}, "Size"),
    h("p", { class: "muted small" }, "The longest side, in nodes. A player is about 2 nodes tall."),
    h("div", { class: "row" }, n, apply, use));
}

function chipGroup(options, selected, multi, onChange, disabled) {
  const box = h("div", { class: "chips" });
  const current = new Set(selected);
  for (const o of options) {
    const c = h("button", { type: "button", class: `chip${current.has(o) ? " on" : ""}`, disabled }, o.replaceAll("_", " "));
    c.addEventListener("click", () => {
      if (multi) {
        if (current.has(o)) current.delete(o); else current.add(o);
      } else {
        current.clear();
        current.add(o);
      }
      box.querySelectorAll(".chip").forEach((el, i) => el.classList.toggle("on", current.has(options[i])));
      onChange([...current]);
    });
    box.append(c);
  }
  return box;
}

function placementPanel(sel, l, vocab, editable) {
  const site = new Set((l.site[0] || "plain").split("+"));
  let exposure = l.exposure, biomes = l.biomes, rarity = l.rarity;
  const rarityWord = Object.entries(vocab.rarity).find(([, v]) => v === rarity);
  const prims = Object.values(vocab.sites).flat().filter((s) => s !== "any");
  const save = h("button", { type: "button", disabled: true }, "Save placement");
  const dirty = () => { save.disabled = !editable; };
  save.addEventListener("click", () => busy(save, async () => {
    await api("/api/landmarks/set", { selector: sel, values: {
      "placement.site": [[...site].join("+") || "any"], "placement.exposure": exposure,
      "placement.biomes": biomes.length ? biomes : ["any"], "placement.rarity": rarity } });
    save.disabled = true;
    toast("Placement saved.");
  }));
  return h("div", { class: "panel" }, h("h3", {}, "Where it appears"),
    h("p", { class: "muted small" }, "Pick what the place must have, together (e.g. cliff and coast)."),
    chipGroup(prims, [...site], true, (v) => { site.clear(); v.forEach((x) => site.add(x)); dirty(); }, !editable),
    h("h3", {}, "Seen from afar?"),
    chipGroup(vocab.exposure, [exposure], false, (v) => { exposure = v[0]; dirty(); }, !editable),
    h("h3", {}, "Climate"),
    chipGroup(vocab.biome_tags, biomes, true, (v) => { biomes = v; dirty(); }, !editable),
    h("h3", {}, "How often"),
    chipGroup(Object.keys(vocab.rarity).sort((a, b) => vocab.rarity[a] - vocab.rarity[b]), rarityWord ? [rarityWord[0]] : [], false, (v) => { rarity = vocab.rarity[v[0]]; dirty(); }, !editable),
    h("p", { class: "muted small" }, `About one in ${rarity} map areas.`),
    h("div", { class: "row end" }, save));
}

function storyPanel(sel, l, editable) {
  const title = h("input", { type: "text", value: l.title, disabled: !editable });
  const lore = h("textarea", { disabled: !editable }, l.lore || "");
  const save = h("button", { type: "button", disabled: !editable }, "Save");
  save.addEventListener("click", () => busy(save, async () => {
    await api("/api/landmarks/set", { selector: sel, values: { title: title.value.trim(), lore: lore.value.trim() } });
    toast("Saved.");
  }));
  return h("div", { class: "panel" }, h("h3", {}, "Name and lore"), h("label", {}, "Name", title), h("label", {}, "Lore", lore), h("div", { class: "row end" }, save));
}

async function checkPanel(sel, editable, frame) {
  const findings = await api(`/api/landmarks/lint?selector=${encodeURIComponent(sel)}`).catch((e) => [{ level: "error", code: "", message: e.message }]);
  const relevant = findings.filter((f) => f.code !== "L003");
  const sealed = relevant.some((f) => f.code === "L016");
  const box = h("div", { class: "panel" }, h("h3", {}, "Check"));
  if (sealed && editable) {
    // the rooms have no way in: offer the bot's /door command per side
    const door = (line, label) => {
      const b = h("button", { type: "button" }, label);
      b.addEventListener("click", () => busy(b, async () => {
        await follow(await api("/api/landmarks/command", { selector: sel, lines: [line] }));
        frame.src = frame.src;
        box.replaceWith(await checkPanel(sel, editable, frame));
      }));
      return b;
    };
    box.append(h("p", { class: "small" }, "There is no way into the rooms. Cut a door (x and z are the sides as the viewer shows them), or keep it sealed:"),
      h("div", { class: "row" }, door("/door +x", "Door +x"), door("/door -x", "Door −x"), door("/door +z", "Door +z"), door("/door -z", "Door −z"), door("/door none", "Sealed on purpose")));
  }
  const rest = relevant.filter((f) => !(sealed && editable && f.code === "L016"));
  if (rest.length) box.append(...rest.map((f) => h("div", { class: `finding ${f.level}` }, f.message)));
  else if (!sealed) box.append(h("p", { class: "muted small" }, "No problems found."));
  return box;
}

async function tourPanel(sel) {
  const games = await api("/api/games").catch(() => []);
  const supported = games.filter((g) => GAMES[g.id]);
  let game = state.status.settings.game || "minetest";
  const pick = h("select", { onchange: (e) => { game = e.target.value; refresh(); } },
    supported.map((g) => h("option", { value: g.id, selected: g.id === game }, `${GAMES[g.id]}${g.synced ? "" : " (download first)"}`)));
  const fresh = h("input", { type: "checkbox" });
  const go = h("button", { class: "primary", type: "button" }, "Start Luanti");
  const get = h("button", { type: "button" }, "Download the game");
  function refresh() {
    const g = supported.find((x) => x.id === game);
    get.classList.toggle("hidden", !g || g.synced);
    go.disabled = !g || !g.synced;
  }
  get.addEventListener("click", () => busy(get, async () => {
    await follow(await api("/api/games/sync", { id: game }));
    const g = supported.find((x) => x.id === game);
    if (g) g.synced = true;
    refresh();
  }));
  go.addEventListener("click", () => busy(go, async () => {
    await follow(await api("/api/tour", { selector: sel, game, fresh: fresh.checked }));
    toast("Luanti is starting. It searches new land until the landmark appears.");
  }));
  refresh();
  return h("div", { class: "panel" }, h("h3", {}, "Walk around it in Luanti"),
    h("p", { class: "muted small" }, "Opens Luanti in a creative test world of its own, flying, and searches for this landmark."),
    h("div", { class: "row" }, pick, get), h("label", { class: "check" }, fresh, "New map"), h("div", { class: "row end" }, go));
}

function submitPanel(status, draft, editable) {
  if (status.clone_mode) {
    return h("div", { class: "panel" }, h("h3", {}, "Share it"), h("p", { class: "muted small" }, `This is your own clone (${status.workspace}): commit and push with git.`));
  }
  if (!editable || !draft) return h("div");
  return h("div", { class: "panel" }, h("h3", {}, "Share it"),
    h("p", { class: "muted small" }, "When you like it, send it to the Sagas project. A maintainer looks at it once; then it goes into the game by itself."),
    sendButton(draft.name));
}

function sendButton(draftName) {
  const b = h("button", { class: "primary", type: "button" }, (state.status.sent || {})[draftName] ? "Send the changes" : "Send it");
  b.addEventListener("click", () => busy(b, async () => {
    if (!state.status.login) await signIn();
    const job = await follow(await api("/api/submit", { draft: draftName }));
    await refreshStatus();
    const sent = job.result;
    toast(sent.direct ? "Committed on main." : `Pull request #${sent.pull} is open.`);
    b.after(h("p", {}, h("a", { href: sent.url, target: "_blank", rel: "noopener" }, sent.direct ? "See the commit on GitHub" : "See your pull request on GitHub")));
  }));
  return b;
}

async function signIn() {
  const r = await api("/api/signin", {});
  const dialog = h("dialog", {},
    h("h2", {}, "Sign in to GitHub"),
    h("p", {}, "Open GitHub and enter this code:"),
    h("p", { class: "code" }, r.user_code),
    h("div", { class: "row" },
      h("a", { class: "button primary", href: r.verification_uri, target: "_blank", rel: "noopener" }, "Open GitHub"),
      h("button", { type: "button", onclick: () => dialog.close() }, "Cancel")),
    h("p", { class: "muted small" }, "Saga Forge may then fork the Sagas project into your account and open pull requests. It never sees your password."));
  document.body.append(dialog);
  dialog.showModal();
  try {
    await follow(r.job);
    await refreshStatus();
  } finally {
    dialog.close();
    dialog.remove();
  }
}

// ---------------------------------------------------------------- my work
async function viewDrafts() {
  const [drafts, status] = await Promise.all([refreshDrafts(), refreshStatus()]);
  const sent = status.sent || {};
  const rows = drafts.map((d) => {
    const open = h("button", { type: "button" }, d.current ? "Current" : "Work on it");
    open.disabled = d.current;
    open.addEventListener("click", () => busy(open, async () => { await api("/api/drafts/open", { name: d.name }); viewDrafts(); }));
    const drop = h("button", { type: "button", class: "danger" }, "Discard");
    drop.addEventListener("click", () => {
      if (!confirm(`Discard the draft "${d.name}"? Its changes are lost.`)) return;
      busy(drop, async () => { await api("/api/drafts/discard", { name: d.name }); viewDrafts(); });
    });
    const s = sent[d.name];
    return h("tr", {},
      h("td", {}, h("strong", {}, d.name), h("div", { class: "muted small" }, d.landmarks.map((sel) => h("a", { href: `#/landmark/${sel}` }, sel, " ")))),
      h("td", {}, s ? h("a", { href: s.url, target: "_blank", rel: "noopener" }, s.direct ? "on main" : `pull request #${s.pull}`) : h("span", { class: "muted" }, "not sent")),
      h("td", {}, h("div", { class: "row" }, open, d.landmarks.length ? sendButton(d.name) : null, drop)));
  });
  const update = h("button", { type: "button" }, "Bring my draft up to date");
  update.addEventListener("click", () => busy(update, async () => {
    try {
      await follow(await api("/api/drafts/update", { keep: "" }));
      toast("Your draft is up to date.");
    } catch (e) {
      if (/same files/.test(e.message) && confirm(`${e.message}\n\nKeep your version? (Cancel takes the newer one from the project.)`)) await follow(await api("/api/drafts/update", { keep: "mine" }));
      else if (/same files/.test(e.message)) await follow(await api("/api/drafts/update", { keep: "theirs" }));
      else throw e;
    }
  }));
  const subs = h("div", {}, status.login ? h("p", { class: "muted" }, h("span", { class: "spinner" }), " Asking GitHub…") : h("p", { class: "muted" }, "Sign in to GitHub (Settings) to see your pull requests here."));
  show(
    h("h1", {}, "My work"),
    status.clone_mode ? h("p", { class: "notice" }, `Saga Forge works in your clone ${status.workspace}; commit and push with git.`) : null,
    h("h2", {}, "Drafts"),
    drafts.length ? h("table", {}, h("tbody", {}, rows)) : h("p", { class: "muted" }, "No drafts yet. Add a landmark, or open one and change it."),
    status.clone_mode ? null : h("div", { class: "row" }, update),
    h("h2", {}, "Sent to the project"), subs);
  if (status.login) {
    api("/api/submissions").then((list) => {
      subs.replaceChildren(list.length ? h("table", {}, h("tbody", {}, list.map((p) => h("tr", {},
        h("td", {}, h("a", { href: p.html_url, target: "_blank", rel: "noopener" }, `#${p.number} ${p.title}`)),
        h("td", {}, p.merged ? "merged" : p.state),
        h("td", {}, { success: "checks passed", failure: "checks failed", pending: "checks running" }[p.checks] || ""),
        h("td", { class: "small" }, p.pictures ? h("a", { href: p.html_url, target: "_blank", rel: "noopener" }, "pictures") : null,
          p.comments && p.comments.length ? ` · ${p.comments.length} comment(s), latest by ${p.comments[p.comments.length - 1].user.login}` : null)))))
        : h("p", { class: "muted" }, "Nothing sent yet."));
    }).catch((e) => subs.replaceChildren(h("p", { class: "notice warn" }, e.message)));
  }
}

// ---------------------------------------------------------------- settings
async function viewSettings() {
  const [status, set, found] = await Promise.all([refreshStatus(), api("/api/settings"), api("/api/installations").catch(() => [])]);
  const game = h("select", {}, Object.entries(GAMES).map(([id, t]) => h("option", { value: id, selected: set.game === id }, t)));
  const lite = h("input", { type: "checkbox", checked: set.lite });
  const bin = h("select", {}, h("option", { value: "" }, "Find it automatically"),
    found.map((b) => h("option", { value: b.path, selected: set.luanti_bin === b.path }, `Luanti ${b.version} (${b.path})`)));
  const custom = h("input", { type: "text", placeholder: "or the full path to luanti / luanti.exe", value: found.some((b) => b.path === set.luanti_bin) ? "" : set.luanti_bin });
  const save = h("button", { class: "primary", type: "button" }, "Save");
  save.addEventListener("click", () => busy(save, async () => {
    await api("/api/settings", { game: game.value, lite: lite.checked, luanti_bin: custom.value.trim() || bin.value });
    toast("Saved.");
  }));
  const account = status.login
    ? h("div", { class: "row" }, h("span", {}, `Signed in as ${status.login}.`), h("button", { type: "button", onclick: async () => { await api("/api/signout", {}); viewSettings(); } }, "Sign out"))
    : h("div", { class: "row" }, h("button", { class: "primary", type: "button", onclick: async (e) => { await busy(e.target, signIn); viewSettings(); } }, "Sign in to GitHub"));
  const update = h("button", { type: "button" }, "Update the tools");
  update.addEventListener("click", () => busy(update, async () => { await follow(await api("/api/setup", { update: true })); toast("The tools are up to date."); }));
  show(
    h("h1", {}, "Settings"),
    h("div", { class: "panel" }, h("h3", {}, "Luanti"),
      h("label", {}, "Game for tours", game),
      h("label", {}, "Luanti program", bin), custom,
      h("label", { class: "check" }, lite, "Lighter graphics (for laptops and 4K screens)"),
      h("div", { class: "row end" }, save)),
    h("div", { class: "panel" }, h("h3", {}, "GitHub"), h("p", { class: "muted small" }, "Needed only to send your work to the Sagas project."), account),
    h("div", { class: "panel" }, h("h3", {}, "Tools"),
      h("p", { class: "muted small" }, `Saga Forge ${status.version} works in ${status.workspace}.`),
      update));
}

route();
