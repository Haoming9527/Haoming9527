// Board manager: edits profile.json for the Haoming9527 profile board.
//
// Security model
// - GitHub decides who can write: saving needs a fine-grained token with write access to this
//   one repository, which only its owner can create. The checks below are defence in depth.
// - The token lives in memory. "Remember" stores it only encrypted with a passphrase
//   (PBKDF2 + AES-GCM), because every Pages site on haoming9527.github.io shares this origin.
// - It is sent only to api.github.com, never rendered, and forgotten after 30 idle minutes.
// - The page writes nothing but profile.json and new files in assets/logos.

if (window.top !== window.self) {
  document.documentElement.textContent = "";
  throw new Error("The board manager refuses to run inside a frame.");
}

const OWNER = "Haoming9527";
const REPO = "Haoming9527";
const BRANCH = "main";
const API = "https://api.github.com";
const RAW = `https://raw.githubusercontent.com/${OWNER}/${REPO}`;
const VAULT_KEY = "board-manager.vault.v1";
const IDLE_LOCK_MS = 30 * 60 * 1000;
const LOGO_FILE = /^[A-Za-z0-9][A-Za-z0-9._-]*\.(svg|png|jpe?g)$/i;
const WRITABLE = [/^profile\.json$/, /^assets\/logos\/[a-z0-9][a-z0-9-]*\.(png|svg)$/];
const TABS = [["watchlist", "Watchlist"], ["collabs", "Collaborations"], ["coverage", "Chart coverage"], ["record", "Track record"]];
const SECTIONS = { watchlist: "projects", collabs: "collaborations", coverage: "activity_repositories", record: "achievements" };

const state = {
  token: "", user: "", config: null, original: null, sha: "", repos: [], external: [], logos: [], commits: {},
  uploads: {}, tab: "watchlist", filter: "", saving: false, busy: false, idleTimer: 0,
};

// ---------------------------------------------------------------- small helpers

const $ = (selector) => document.querySelector(selector);
const utf8 = (text) => new TextEncoder().encode(text);
const toBase64 = (bytes) => { let s = ""; for (const b of bytes) s += String.fromCharCode(b); return btoa(s); };
const fromBase64 = (text) => Uint8Array.from(atob(text.replace(/\s/g, "")), (c) => c.charCodeAt(0));
const clone = (value) => JSON.parse(JSON.stringify(value));

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "value") el.value = value;
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));   // never innerHTML
  }
  return el;
}

function toast(message, link) {
  const box = $("#toast");
  box.replaceChildren(message, link ? h("span", {}, " ", h("a", { href: link.href, rel: "noopener" }, link.label)) : "");
  box.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => box.classList.remove("show"), 6000);
}

const compact = (v) => Array.isArray(v) ? `[${v.map(compact).join(", ")}]`
  : v && typeof v === "object" ? `{${Object.entries(v).map(([k, x]) => `${JSON.stringify(k)}: ${compact(x)}`).join(", ")}}`
  : JSON.stringify(v);

/** profile.json in its existing style: one line per list item. */
function formatConfig(config) {
  const keys = Object.keys(config);
  const lines = keys.map((key, i) => {
    const value = config[key];
    const tail = i < keys.length - 1 ? "," : "";
    if (Array.isArray(value) && value.length) {
      const items = value.map((item, j) => `    ${compact(item)}${j < value.length - 1 ? "," : ""}`);
      return `  ${JSON.stringify(key)}: [\n${items.join("\n")}\n  ]${tail}`;
    }
    return `  ${JSON.stringify(key)}: ${compact(value)}${tail}`;
  });
  return `{\n${lines.join("\n")}\n}\n`;
}

const prettyName = (repo) => repo.split("/").pop().replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim();

function suggestTicker(name) {
  const words = name.split(/[-_\s.]+/).filter(Boolean);
  const value = words.length > 1 ? words.map((w) => w[0]).join("") : name.replace(/[^A-Za-z0-9]/g, "").slice(0, 4);
  return value.toUpperCase().slice(0, 5);
}

function since(iso) {
  const days = Math.floor((Date.now() - Date.parse(iso)) / 86_400_000);
  return days < 1 ? "today" : days < 30 ? `${days}d ago` : days < 365 ? `${Math.floor(days / 30)}mo ago` : `${Math.floor(days / 365)}y ago`;
}

// ---------------------------------------------------------------- GitHub API

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (body) headers["Content-Type"] = "application/json";
  const response = await fetch(API + path, { method, headers, body: body && JSON.stringify(body), cache: "no-store",
    credentials: "omit", referrerPolicy: "no-referrer" });
  if (!response.ok) {
    let message = response.statusText;
    try { message = (await response.json()).message || message; } catch { /* keep status text */ }
    throw new ApiError(response.status, message);
  }
  return response.status === 204 ? null : response.json();
}

async function ownedRepos() {
  const repos = [];
  for (let page = 1; page < 10; page++) {
    const batch = await api(`/users/${OWNER}/repos?type=owner&per_page=100&page=${page}`);
    repos.push(...batch);
    if (batch.length < 100) break;
  }
  return repos.filter((repo) => !repo.private && repo.full_name.toLowerCase() !== `${OWNER}/${REPO}`.toLowerCase())
    .sort((a, b) => b.pushed_at.localeCompare(a.pushed_at));
}

async function load() {
  const [repos, file, logos, snapshot] = await Promise.all([
    ownedRepos(),
    api(`/repos/${OWNER}/${REPO}/contents/profile.json?ref=${BRANCH}`),
    api(`/repos/${OWNER}/${REPO}/contents/assets/logos?ref=${BRANCH}`),
    fetch(`${RAW}/market/data/activity.json`, { cache: "no-store", credentials: "omit" })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  state.repos = repos;
  state.sha = file.sha;
  state.config = JSON.parse(new TextDecoder().decode(fromBase64(file.content)));
  state.original = clone(state.config);
  state.logos = logos.filter((f) => f.type === "file" && LOGO_FILE.test(f.name)).map((f) => f.name).sort();
  state.uploads = {};
  state.commits = Object.fromEntries((snapshot?.repositories || []).map((row) => [row.name.toLowerCase(), row.shas?.length || 0]));
  const external = new Map((snapshot?.open_source?.repositories || []).map((row) => [row.name.toLowerCase(), row]));
  for (const entry of state.config.collaborations || []) {
    if (!external.has(entry.repository.toLowerCase())) external.set(entry.repository.toLowerCase(), { name: entry.repository });
  }
  state.external = [...external.values()].sort((a, b) => (b.merged_prs || 0) - (a.merged_prs || 0));
}

// ---------------------------------------------------------------- token: memory first, encrypted if remembered

async function deriveKey(passphrase, salt) {
  const base = await crypto.subtle.importKey("raw", utf8(passphrase), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations: 310_000, hash: "SHA-256" }, base,
    { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

async function rememberToken(token, passphrase) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await deriveKey(passphrase, salt), utf8(token)));
  localStorage.setItem(VAULT_KEY, JSON.stringify({ salt: toBase64(salt), iv: toBase64(iv), data: toBase64(data) }));
}

async function unlockToken(passphrase) {
  const vault = JSON.parse(localStorage.getItem(VAULT_KEY));
  const key = await deriveKey(passphrase, fromBase64(vault.salt));
  try {
    return new TextDecoder().decode(await crypto.subtle.decrypt({ name: "AES-GCM", iv: fromBase64(vault.iv) }, key, fromBase64(vault.data)));
  } catch {
    throw new Error("That passphrase doesn't unlock the saved token.");
  }
}

async function connect(token) {
  token = token.trim();
  if (!token.startsWith("github_pat_")) {
    throw new Error("Use a fine-grained token (it starts with github_pat_). Classic tokens can reach all your repositories.");
  }
  state.token = token;
  try {
    const user = await api("/user");
    if (user.login.toLowerCase() !== OWNER.toLowerCase()) throw new Error(`This token belongs to ${user.login}; only ${OWNER} can save.`);
    state.user = user.login;
  } catch (error) {
    state.token = "";
    state.user = "";
    throw error.status === 401 ? new Error("GitHub rejected that token. It may have expired or been revoked.") : error;
  }
  armIdleLock();
}

function lock(message = "Locked. The token is no longer in memory.") {
  state.token = "";
  state.user = "";
  clearTimeout(state.idleTimer);
  renderToken();
  renderFooter();
  toast(message);
}

function armIdleLock() {
  clearTimeout(state.idleTimer);
  if (state.token) state.idleTimer = setTimeout(() => lock("Locked after 30 minutes without activity."), IDLE_LOCK_MS);
}
["pointerdown", "keydown"].forEach((type) => window.addEventListener(type, armIdleLock, { passive: true }));

// ---------------------------------------------------------------- changes and validation

function changedSections() {
  return TABS.filter(([tab]) => JSON.stringify(state.config[SECTIONS[tab]] || []) !== JSON.stringify(state.original[SECTIONS[tab]] || []))
    .map(([, label]) => label);
}

function problems() {
  const c = state.config;
  const list = [];
  const logoOk = (file) => file && (state.logos.includes(file) || state.uploads[file]);
  if (!(c.activity_repositories || []).length) list.push("Chart coverage needs at least one repository.");
  (c.projects || []).forEach((p) => {
    const where = p.name || p.repository;
    if (!p.name?.trim()) list.push(`Watchlist: ${p.repository} needs a name.`);
    if (!/^[A-Z0-9]{1,6}$/.test(p.ticker || "")) list.push(`Watchlist: ${where} needs a ticker of 1 to 6 letters or digits.`);
    if (!logoOk(p.logo)) list.push(`Watchlist: ${where} needs a logo.`);
  });
  (c.collaborations || []).forEach((e) => {
    if (!e.name?.trim()) list.push(`Collaborations: ${e.repository} needs a name.`);
    const ok = e.wordmark ? logoOk(e.wordmark.light) && logoOk(e.wordmark.dark) : logoOk(e.logo);
    if (!ok) list.push(`Collaborations: ${e.name || e.repository} needs ${e.wordmark ? "light and dark wordmarks" : "a logo"}.`);
  });
  (c.achievements || []).forEach((a, i) => {
    const where = a.event || `achievement ${i + 1}`;
    for (const key of ["rank", "event", "tag"]) if (!a[key]?.trim()) list.push(`Track record: ${where} needs a ${key}.`);
    if (!/^https:\/\/[^\s]+$/.test(a.url || "")) list.push(`Track record: ${where} needs a link starting with https://.`);
    if (!logoOk(a.logo)) list.push(`Track record: ${where} needs a logo.`);
  });
  return list;
}

function edited() {
  renderTape();
  renderFooter();
}

// ---------------------------------------------------------------- logos

const logoUrl = (file) => state.uploads[file]?.preview || `${RAW}/${BRANCH}/assets/logos/${encodeURIComponent(file)}`;

function disc(file, kind = "") {
  return h("span", { class: `disc ${kind}${file ? "" : " empty"}`, "aria-hidden": "true" },
    file ? h("img", { src: logoUrl(file), alt: "", referrerpolicy: "no-referrer" }) : null);
}

function uniqueName(base, ext) {
  const slug = (base.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "logo").slice(0, 40);
  let name = `${slug}.${ext}`;
  for (let n = 2; state.logos.includes(name) || state.uploads[name]; n++) name = `${slug}-${n}.${ext}`;
  return name;
}

async function prepareLogo(file, base) {
  if (file.size > 2_000_000) throw new Error("Pick an image under 2 MB.");
  if (/\.svg$/i.test(file.name) || file.type === "image/svg+xml") {
    const text = await file.text();
    if (!/<svg[\s>]/i.test(text) || /<script|<foreignObject|\son[a-z]+\s*=|javascript:|<!ENTITY/i.test(text)) {
      throw new Error("That SVG contains scripts or isn't a plain SVG. Use another file or a PNG.");
    }
    if (text.length > 100_000) throw new Error("Keep SVG logos under 100 KB.");
    const base64 = toBase64(utf8(text));
    return { name: uniqueName(base, "svg"), base64, preview: `data:image/svg+xml;base64,${base64}` };
  }
  if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) throw new Error("Use a PNG, JPEG, WebP or SVG file.");
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 192 / Math.max(bitmap.width, bitmap.height));   // small: logos are embedded in every widget
  const canvas = h("canvas", { width: Math.max(1, Math.round(bitmap.width * scale)), height: Math.max(1, Math.round(bitmap.height * scale)) });
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const preview = canvas.toDataURL("image/png");
  return { name: uniqueName(base, "png"), base64: preview.split(",")[1], preview };
}

function pickFile() {
  return new Promise((resolve) => {
    const input = h("input", { type: "file", accept: ".png,.jpg,.jpeg,.webp,.svg,image/png,image/jpeg,image/webp,image/svg+xml" });
    input.addEventListener("change", () => resolve(input.files[0] || null));
    input.addEventListener("cancel", () => resolve(null));
    input.click();
  });
}

function logoSelect(value, base, onPick, label = "Logo") {
  const files = [...new Set([...state.logos, ...Object.keys(state.uploads)])].sort();
  return h("label", {}, label,
    h("select", {
      onchange: async (event) => {
        const choice = event.target.value;
        if (choice !== "__upload__") { onPick(choice); renderPanel(); edited(); return; }
        try {
          const file = await pickFile();
          if (file) {
            const logo = await prepareLogo(file, base);
            state.uploads[logo.name] = logo;
            onPick(logo.name);
            toast(`${logo.name} will be uploaded when you save.`);
          }
        } catch (error) {
          toast(error.message);
        }
        renderPanel();
        edited();
      },
    },
    h("option", { value: "", selected: !value }, "Choose a logo…"),
    files.map((file) => h("option", { value: file, selected: file === value }, state.uploads[file] ? `${file} (new)` : file)),
    h("option", { value: "__upload__" }, "Upload a new logo…")));
}

// ---------------------------------------------------------------- shared list pieces

function textField(label, value, onInput, attrs = {}) {
  return h("label", { class: attrs.wide ? "wide" : null }, label,
    h("input", { type: attrs.type || "text", value: value || "", maxlength: attrs.maxlength || 120, placeholder: attrs.placeholder,
      autocomplete: "off", spellcheck: attrs.spellcheck ?? "true",
      oninput: (event) => { onInput(event.target.value); edited(); } }));
}

function move(list, from, to) {
  if (to < 0 || to >= list.length || from === to) return;
  list.splice(to, 0, list.splice(from, 1)[0]);
  renderPanel();
  edited();
}

function sortableItem(list, index, children) {
  const item = h("li", { class: "item" },
    h("span", { class: "handle", draggable: "true", title: "Drag to reorder", "aria-hidden": "true",
      ondragstart: (event) => { event.dataTransfer.setData("text/plain", String(index)); event.dataTransfer.setDragImage(item, 24, 24); } },
    "⠿"),
    children,
    h("div", { class: "actions" },
      h("button", { class: "icon", type: "button", "aria-label": "Move up", title: "Move up", onclick: () => move(list, index, index - 1) }, "▲"),
      h("button", { class: "icon", type: "button", "aria-label": "Move down", title: "Move down", onclick: () => move(list, index, index + 1) }, "▼"),
      h("button", { class: "icon", type: "button", "aria-label": "Remove", title: "Remove",
        onclick: () => { list.splice(index, 1); renderPanel(); edited(); } }, "✕")));
  item.addEventListener("dragover", (event) => { event.preventDefault(); item.classList.add("drop"); });
  item.addEventListener("dragleave", () => item.classList.remove("drop"));
  item.addEventListener("drop", (event) => {
    event.preventDefault();
    item.classList.remove("drop");
    move(list, Number(event.dataTransfer.getData("text/plain")), index);
  });
  return item;
}

function picker(items, isOn, toggle, describe, lockedReason) {
  const query = state.filter.toLowerCase();
  const shown = items.filter((item) => describe(item).title.toLowerCase().includes(query));
  return h("ul", { class: "picker" }, shown.length ? shown.map((item) => {
    const { title, sub } = describe(item);
    const locked = lockedReason?.(item);
    return h("li", {}, h("label", { title: locked || null },
      h("input", { type: "checkbox", checked: isOn(item), disabled: Boolean(locked),
        onchange: (event) => { toggle(item, event.target.checked); renderPanel(); edited(); } }),
      h("span", {}, h("span", { class: "name" }, title), h("span", { class: "sub" }, locked || sub))));
  }) : h("li", { class: "hint" }, "Nothing matches that filter."));
}

function filterBox() {
  return h("input", { type: "search", placeholder: "Filter repositories", value: state.filter, "aria-label": "Filter repositories",
    oninput: (event) => { state.filter = event.target.value; const list = $("#panel .picker"); if (list) list.replaceWith(currentPicker()); } });
}

const repoLine = (repo) => [repo.language, repo.stargazers_count ? `★ ${repo.stargazers_count}` : "",
  state.commits[repo.full_name.toLowerCase()] ? `${state.commits[repo.full_name.toLowerCase()]} commits` : "", `pushed ${since(repo.pushed_at)}`,
  repo.fork ? "fork" : "", repo.archived ? "archived" : ""].filter(Boolean).join(" · ");

// ---------------------------------------------------------------- sections

function ensureCoverage(repository) {
  const coverage = state.config.activity_repositories ||= [];
  if (!coverage.some((name) => name.toLowerCase() === repository.toLowerCase())) coverage.push(repository);
}

function watchlistPicker() {
  const projects = state.config.projects ||= [];
  return picker(state.repos,
    (repo) => projects.some((p) => p.repository.toLowerCase() === repo.full_name.toLowerCase()),
    (repo, on) => {
      if (on) {
        const name = prettyName(repo.full_name);
        projects.push({ repository: repo.full_name, name, ticker: suggestTicker(name), logo: "" });
        ensureCoverage(repo.full_name);
      } else {
        projects.splice(projects.findIndex((p) => p.repository.toLowerCase() === repo.full_name.toLowerCase()), 1);
      }
    },
    (repo) => ({ title: repo.name, sub: repoLine(repo) }));
}

function watchlistPanel() {
  const projects = state.config.projects ||= [];
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Watchlist"),
      h("p", {}, "Projects shown as rows with a chart line. Drag to reorder; adding one also adds it to chart coverage.")),
    h("div", { class: "columns" },
      h("div", {}, h("h3", {}, `On the board (${projects.length})`),
        projects.length ? h("ol", { class: "sortable" }, projects.map((p, i) => sortableItem(projects, i, [
          disc(p.logo, p.logo_fit === "contain" ? "" : "cover"),
          h("div", { class: "fields" },
            textField("Name", p.name, (v) => { p.name = v; }),
            textField("Ticker", p.ticker, (v) => { p.ticker = v.toUpperCase().replace(/[^A-Z0-9]/g, ""); }, { maxlength: 6, spellcheck: "false" }),
            logoSelect(p.logo, p.repository.split("/").pop(), (file) => { p.logo = file; }),
            h("label", {}, "Logo fit", h("select", { onchange: (e) => { if (e.target.value === "cover") delete p.logo_fit; else p.logo_fit = "contain"; renderPanel(); edited(); } },
              h("option", { value: "cover", selected: p.logo_fit !== "contain" }, "Fill the circle"),
              h("option", { value: "contain", selected: p.logo_fit === "contain" }, "Fit inside"))),
            h("p", { class: "meta" }, p.repository)),
        ]))) : h("p", { class: "empty-state" }, "Pick projects from your repositories.")),
      h("div", {}, h("h3", {}, "Your public repositories"), filterBox(), watchlistPicker())),
  ];
}

function collabsPicker() {
  const collabs = state.config.collaborations ||= [];
  return picker(state.external,
    (repo) => collabs.some((e) => e.repository.toLowerCase() === repo.name.toLowerCase()),
    (repo, on) => {
      if (on) collabs.push({ repository: repo.name, name: repo.name.split("/").pop(), logo: "" });
      else collabs.splice(collabs.findIndex((e) => e.repository.toLowerCase() === repo.name.toLowerCase()), 1);
    },
    (repo) => ({ title: repo.name, sub: [repo.merged_prs ? `${repo.merged_prs} merged PRs` : "", repo.language,
      repo.stars ? `★ ${repo.stars}` : ""].filter(Boolean).join(" · ") }));
}

function collabsPanel() {
  const collabs = state.config.collaborations ||= [];
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Collaborations"),
      h("p", {}, "Other people's projects that merged your pull requests. A wordmark replaces the logo and the name.")),
    h("div", { class: "columns" },
      h("div", {}, h("h3", {}, `On the board (${collabs.length})`),
        collabs.length ? h("ol", { class: "sortable" }, collabs.map((e, i) => sortableItem(collabs, i, [
          e.wordmark ? disc(e.wordmark.light, "wordmark") : disc(e.logo, "cover"),
          h("div", { class: "fields" },
            textField("Name", e.name, (v) => { e.name = v; }),
            h("label", {}, "Shown as", h("select", {
              onchange: (event) => {
                if (event.target.value === "wordmark") { delete e.logo; e.wordmark = { light: "", dark: "" }; }
                else { delete e.wordmark; e.logo = ""; }
                renderPanel(); edited();
              } },
            h("option", { value: "logo", selected: !e.wordmark }, "Logo + name"),
            h("option", { value: "wordmark", selected: Boolean(e.wordmark) }, "Wordmark"))),
            e.wordmark
              ? [logoSelect(e.wordmark.light, `${e.name}-light`, (f) => { e.wordmark.light = f; }, "Wordmark (light theme)"),
                logoSelect(e.wordmark.dark, `${e.name}-dark`, (f) => { e.wordmark.dark = f; }, "Wordmark (dark theme)")]
              : logoSelect(e.logo, e.repository.split("/").pop(), (f) => { e.logo = f; }),
            h("p", { class: "meta" }, e.repository)),
        ]))) : h("p", { class: "empty-state" }, "Pick projects you have contributed to.")),
      h("div", {}, h("h3", {}, "Repositories with your merged pull requests"), filterBox(), collabsPicker())),
  ];
}

function coveragePicker() {
  const coverage = state.config.activity_repositories ||= [];
  const has = (name) => coverage.some((x) => x.toLowerCase() === name.toLowerCase());
  const watched = (name) => (state.config.projects || []).some((p) => p.repository.toLowerCase() === name.toLowerCase());
  return h("div", { class: "grid picker" }, state.repos.filter((r) => r.name.toLowerCase().includes(state.filter.toLowerCase())).map((repo) =>
    h("label", { title: watched(repo.full_name) ? "On the watchlist, so it stays in the chart" : null },
      h("input", { type: "checkbox", checked: has(repo.full_name), disabled: watched(repo.full_name),
        onchange: (event) => {
          if (event.target.checked) coverage.push(repo.full_name);
          else coverage.splice(coverage.findIndex((x) => x.toLowerCase() === repo.full_name.toLowerCase()), 1);
          renderPanel(); edited();
        } }),
      h("span", {}, h("span", { class: "name" }, repo.name),
        h("span", { class: "sub" }, watched(repo.full_name) ? "On the watchlist" : repoLine(repo))))));
}

function coveragePanel() {
  const coverage = state.config.activity_repositories ||= [];
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Chart coverage"),
      h("p", {}, "Repositories whose commits feed the candles, the commit index, languages and the tech stack.")),
    h("div", { class: "toolbar" }, filterBox(),
      h("button", { class: "btn small", type: "button", onclick: () => {
        for (const repo of state.repos) if (!coverage.some((x) => x.toLowerCase() === repo.full_name.toLowerCase())) coverage.push(repo.full_name);
        renderPanel(); edited(); } }, "Select all"),
      h("span", { class: "hint" }, `${coverage.length} of ${state.repos.length} selected`)),
    coveragePicker(),
  ];
}

function recordPanel() {
  const record = state.config.achievements ||= [];
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Track record"),
      h("p", {}, "Achievement tiles, two per row. The tag shows on the tile; the link opens when someone clicks it.")),
    record.length ? h("ol", { class: "sortable" }, record.map((a, i) => sortableItem(record, i, [
      disc(a.logo, "square"),
      h("div", { class: "fields" },
        textField("Result", a.rank, (v) => { a.rank = v; }, { placeholder: "Winner, Top 10…" }),
        textField("Event", a.event, (v) => { a.event = v; }, { placeholder: "Hackathon or award", wide: false }),
        textField("Tag", a.tag, (v) => { a.tag = v; }, { placeholder: "Project or year", maxlength: 30 }),
        textField("Link", a.url, (v) => { a.url = v.trim(); }, { type: "url", placeholder: "https://", spellcheck: "false", maxlength: 300 }),
        logoSelect(a.logo, a.event || "achievement", (f) => { a.logo = f; })),
    ]))) : h("p", { class: "empty-state" }, "No achievements yet."),
    h("div", { class: "toolbar", style: null },
      h("button", { class: "btn", type: "button", onclick: () => { record.push({ rank: "", event: "", tag: "", logo: "", url: "" }); renderPanel(); edited(); } },
        "Add an achievement")),
  ];
}

const PANELS = { watchlist: watchlistPanel, collabs: collabsPanel, coverage: coveragePanel, record: recordPanel };
const PICKERS = { watchlist: watchlistPicker, collabs: collabsPicker, coverage: coveragePicker };
const currentPicker = () => PICKERS[state.tab]();

// ---------------------------------------------------------------- rendering

function renderTape() {
  const changed = new Set(changedSections());
  const c = state.config;
  $("#tape").replaceChildren(...[["WATCHLIST", c.projects, "Watchlist"], ["COLLAB", c.collaborations, "Collaborations"],
    ["COVERAGE", c.activity_repositories, "Chart coverage"], ["AWARDS", c.achievements, "Track record"]].map(([label, list, section]) =>
    h("span", { class: changed.has(section) ? "changed" : null }, h("b", {}, label), (list || []).length, changed.has(section) ? " ▲ edited" : "")));
}

function renderToken() {
  const box = $("#token");
  const saved = Boolean(localStorage.getItem(VAULT_KEY));
  const guide = h("details", {}, h("summary", {}, "How to create the token"),
    h("ol", {},
      h("li", {}, "GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token."),
      h("li", {}, "Resource owner: Haoming9527. Expiration: 90 days or less."),
      h("li", {}, "Repository access: Only select repositories → Haoming9527/Haoming9527."),
      h("li", {}, "Permissions → Repository → Contents: Read and write. Nothing else."),
      h("li", {}, "Generate, copy it, and paste it here. GitHub shows it only once.")));
  if (state.user) {
    box.replaceChildren(h("div", { class: "row" },
      h("span", { class: "status" }, h("span", { class: "dot on" }), `Connected as ${state.user}. Saving is unlocked.`),
      h("button", { class: "btn small", type: "button", onclick: () => lock() }, "Lock"),
      h("button", { class: "btn small danger", type: "button", onclick: () => { localStorage.removeItem(VAULT_KEY); lock("Token forgotten on this device."); } },
        "Forget token")),
    h("p", { class: "hint" }, "Locks itself after 30 minutes without activity."));
    return;
  }
  const message = h("p", { class: "hint error", role: "alert" });
  const fail = (error) => { message.textContent = error.message; };
  if (saved) {
    const pass = h("input", { type: "password", placeholder: "Passphrase", autocomplete: "current-password", "aria-label": "Passphrase" });
    const unlock = async () => {
      try { await connect(await unlockToken(pass.value)); renderToken(); renderFooter(); toast("Unlocked. Saving is unlocked."); }
      catch (error) { fail(error); }
    };
    pass.addEventListener("keydown", (e) => { if (e.key === "Enter") unlock(); });
    box.replaceChildren(h("div", { class: "row" }, h("span", { class: "status" }, h("span", { class: "dot" }), "Read-only. A saved token is locked."),
      pass, h("button", { class: "btn primary", type: "button", onclick: unlock }, "Unlock"),
      h("button", { class: "btn small danger", type: "button", onclick: () => { localStorage.removeItem(VAULT_KEY); renderToken(); } }, "Forget saved token")),
    message);
    return;
  }
  const token = h("input", { type: "password", placeholder: "github_pat_…", autocomplete: "off", spellcheck: "false", "aria-label": "Fine-grained token" });
  const remember = h("input", { type: "checkbox", id: "remember" });
  const pass = h("input", { type: "password", placeholder: "Passphrase to lock it (8+ characters)", autocomplete: "new-password",
    "aria-label": "Passphrase", hidden: true });
  remember.addEventListener("change", () => { pass.hidden = !remember.checked; });
  const go = async () => {
    try {
      if (remember.checked && pass.value.length < 8) throw new Error("Choose a passphrase of at least 8 characters to remember the token.");
      await connect(token.value);
      if (remember.checked) await rememberToken(state.token, pass.value);
      renderToken();
      renderFooter();
      toast(remember.checked ? "Connected. The token is saved, encrypted with your passphrase." : "Connected for this visit.");
    } catch (error) { fail(error); }
  };
  token.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  box.replaceChildren(h("div", { class: "row" }, h("span", { class: "status" }, h("span", { class: "dot" }), "Read-only. Anyone can look; only you can save."),
    token, h("button", { class: "btn primary", type: "button", onclick: go }, "Connect")),
  h("div", { class: "row" }, h("label", { class: "hint" }, remember, " Remember on this device, locked with a passphrase"), pass),
  message, guide);
}

function renderTabs() {
  const counts = { watchlist: state.config.projects, collabs: state.config.collaborations,
    coverage: state.config.activity_repositories, record: state.config.achievements };
  $("#tabs").replaceChildren(...TABS.map(([tab, label]) => h("button", { type: "button", role: "tab", "aria-selected": String(state.tab === tab),
    onclick: () => { state.tab = tab; state.filter = ""; renderTabs(); renderPanel(); } },
  label, h("span", { class: "count" }, (counts[tab] || []).length))));
}

function renderPanel() {
  $("#panel").replaceChildren(...PANELS[state.tab]());
}

function renderFooter() {
  const changes = changedSections();
  const uploads = Object.keys(state.uploads).length;
  const issues = changes.length || uploads ? problems() : [];
  const dirty = changes.length > 0 || uploads > 0;
  const summary = dirty ? `Unsaved: ${[...changes, uploads ? `${uploads} new logo${uploads > 1 ? "s" : ""}` : ""].filter(Boolean).join(", ")}`
    : "No unsaved changes";
  const canSave = dirty && !issues.length && state.user && !state.saving;
  $("#footer").replaceChildren(h("div", { class: "inner" },
    h("div", {}, h("strong", {}, summary), issues.length ? h("ul", { class: "error" }, issues.slice(0, 4).map((i) => h("li", {}, i))) : null),
    h("div", { class: "buttons" },
      h("button", { class: "btn", type: "button", disabled: !dirty || state.saving,
        onclick: () => { state.config = clone(state.original); state.uploads = {}; renderAll(); } }, "Discard"),
      h("button", { class: "btn primary", type: "button", disabled: !canSave, onclick: save },
        state.saving ? "Saving…" : state.user ? "Save to profile" : "Connect a token to save"))));
}

function renderAll() {
  renderTape();
  renderToken();
  renderTabs();
  renderPanel();
  renderFooter();
}

// ---------------------------------------------------------------- saving: one commit, fast-forward only

async function save() {
  if (problems().length || !state.user) return;
  state.saving = true;
  renderFooter();
  try {
    const files = [{ path: "profile.json", content: toBase64(utf8(formatConfig(state.config))) },
      ...Object.values(state.uploads).map((u) => ({ path: `assets/logos/${u.name}`, content: u.base64 }))];
    if (!files.every((f) => WRITABLE.some((rule) => rule.test(f.path)))) throw new Error("Refusing to write outside profile.json and assets/logos.");
    const repo = `/repos/${OWNER}/${REPO}`;
    const head = (await api(`${repo}/git/ref/heads/${BRANCH}`)).object.sha;
    const current = await api(`${repo}/contents/profile.json?ref=${head}`);
    if (current.sha !== state.sha) throw new Error("profile.json changed on GitHub since this page loaded. Reload, then make your changes again.");
    const base = (await api(`${repo}/git/commits/${head}`)).tree.sha;
    const tree = [];
    for (const file of files) {
      const blob = await api(`${repo}/git/blobs`, { method: "POST", body: { content: file.content, encoding: "base64" } });
      tree.push({ path: file.path, mode: "100644", type: "blob", sha: blob.sha });
    }
    const newTree = await api(`${repo}/git/trees`, { method: "POST", body: { base_tree: base, tree } });
    const commit = await api(`${repo}/git/commits`, { method: "POST",
      body: { message: "Update the profile board from the dashboard", tree: newTree.sha, parents: [head] } });
    await api(`${repo}/git/refs/heads/${BRANCH}`, { method: "PATCH", body: { sha: commit.sha, force: false } });
    await load();
    renderAll();
    toast("Saved. The profile redraws in about two minutes.",
      { href: `https://github.com/${OWNER}/${REPO}/actions/workflows/update-market.yml`, label: "Watch the refresh" });
  } catch (error) {
    const hint = error.status === 403 || error.status === 404
      ? " Check that the token has Contents: Read and write on Haoming9527/Haoming9527."
      : error.status === 422 ? " The branch moved while saving; try again." : "";
    toast(`Not saved: ${error.message}.${hint}`);
  } finally {
    state.saving = false;
    renderFooter();
  }
}

// ---------------------------------------------------------------- start

window.addEventListener("beforeunload", (event) => {
  if (changedSections().length || Object.keys(state.uploads).length) event.preventDefault();
});

(async () => {
  try {
    await load();
    renderAll();
  } catch (error) {
    $("#panel").replaceChildren(h("p", { class: "error" }, `Couldn't load the profile settings: ${error.message}.`),
      h("p", { class: "hint" }, error.status === 403 ? "GitHub's limit for anonymous requests is used up. Wait a few minutes and reload." : "Reload to try again."));
    renderToken();
  }
})();
