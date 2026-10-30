// The board model: loads profile.json and the logo library, tracks edits, validates them and
// saves everything as one fast-forward commit. No DOM here.

import { BANNER_FILE, BRANCH, DELETABLE, LOGO_FILE, OWNER, RAW, REPO, SECTIONS, TABS, WRITABLE } from "./config.js";
import { api, ownedRepos } from "./github.js";
import { clone, formatConfig, fromBase64, toBase64, utf8 } from "./lib/format.js";
import { state } from "./state.js";

export async function load() {
  const [repos, file, logos, banners, snapshot, catalog] = await Promise.all([
    ownedRepos(),
    api(`/repos/${OWNER}/${REPO}/contents/profile.json?ref=${BRANCH}`),
    api(`/repos/${OWNER}/${REPO}/contents/assets/logos?ref=${BRANCH}`),
    api(`/repos/${OWNER}/${REPO}/contents/assets/banners?ref=${BRANCH}`).catch((error) => { if (error.status === 404) return []; throw error; }),
    fetch(`${RAW}/market/data/activity.json`, { cache: "no-store", credentials: "omit" })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null),
    fetch(`${RAW}/${BRANCH}/scripts/catalog.py`, { cache: "no-store", credentials: "omit" })
      .then((r) => (r.ok ? r.text() : "")).catch(() => ""),
  ]);
  state.repos = repos;
  state.sha = file.sha;
  state.config = JSON.parse(new TextDecoder().decode(fromBase64(file.content)));
  state.original = clone(state.config);
  state.logos = logos.filter((f) => f.type === "file" && LOGO_FILE.test(f.name)).map((f) => f.name).sort();
  state.uploads = {};
  state.banners = banners.filter((f) => f.type === "file" && BANNER_FILE.test(f.name)).map((f) => f.name).sort();
  state.bannerUploads = {};
  state.deletions = new Set();
  // Language and tool logos used by the renderer itself (catalog.VENDORED) can never be deleted.
  const vendored = /VENDORED = \{([\s\S]*?)\n\}/.exec(catalog)?.[1] || "";
  state.protected = new Set([...vendored.matchAll(/"([A-Za-z0-9._-]+\.(?:svg|png|jpe?g))"/gi)].map((m) => m[1]));
  state.protectedKnown = state.protected.size > 0;
  state.snapshotMissing = !snapshot;
  state.commits = Object.fromEntries((snapshot?.repositories || []).map((row) => [row.name.toLowerCase(), row.shas?.length || 0]));
  const external = new Map((snapshot?.open_source?.repositories || []).map((row) => [row.name.toLowerCase(), row]));
  for (const entry of state.config.collaborations || []) {
    if (!external.has(entry.repository.toLowerCase())) external.set(entry.repository.toLowerCase(), { name: entry.repository });
  }
  state.external = [...external.values()].sort((a, b) => (b.merged_prs || 0) - (a.merged_prs || 0));
}

export function changedSections() {
  return TABS.filter(([tab]) => SECTIONS[tab] && JSON.stringify(state.config[SECTIONS[tab]] || []) !== JSON.stringify(state.original[SECTIONS[tab]] || []))
    .map(([, label]) => label);
}

export const isDirty = () => Boolean(state.config) && (changedSections().length > 0 || Object.keys(state.uploads).length > 0
  || Object.keys(state.bannerUploads).length > 0 || state.deletions.size > 0);

export function discard() {
  state.config = clone(state.original);
  state.uploads = {};
  state.bannerUploads = {};
  state.deletions = new Set();
}

const sameRepo = (a, b) => a.toLowerCase() === b.toLowerCase();
export const isExcluded = (repository) => (state.config.activity_exclusions || []).some((name) => sameRepo(name, repository));

/** The charts count every public repository the owner has, new ones included, except forks and exclusions. */
export const countedRepos = () => state.repos.filter((repo) => !repo.fork && !isExcluded(repo.full_name));

export function setCounted(repository, counted) {
  const exclusions = state.config.activity_exclusions ||= [];
  const at = exclusions.findIndex((name) => sameRepo(name, repository));
  if (counted && at >= 0) exclusions.splice(at, 1);
  else if (!counted && at < 0) exclusions.push(repository);
}

/** A watchlist project always counts in the charts, or its row would be empty. */
export const ensureCoverage = (repository) => setCounted(repository, true);

/** Files chosen for an entry: its two wordmarks, or its logo. */
const entryFiles = (entry) => (entry.wordmark ? [entry.wordmark.light, entry.wordmark.dark] : [entry.logo]);

/** Which board entries use each logo file. */
export function logoUsage() {
  const usage = new Map();
  const use = (file, who) => { if (file) usage.set(file, [...(usage.get(file) || []), who]); };
  for (const p of state.config.projects || []) entryFiles(p).forEach((file) => use(file, p.name));
  for (const e of state.config.collaborations || []) entryFiles(e).forEach((file) => use(file, e.name));
  for (const a of state.config.achievements || []) use(a.logo, a.event || "an achievement");
  return usage;
}

/** Why a logo can't be deleted, or "" when it can. */
export function deleteBlocker(file, usage = logoUsage()) {
  const users = [...new Set(usage.get(file) || [])];
  if (users.length) return `Used by ${users.join(", ")}`;
  if (state.protected.has(file)) return "Used for a language or tool logo";
  if (!state.protectedKnown) return "Deleting is off: the language and tool logo list couldn't be read";
  return "";
}

export function problems() {
  const c = state.config;
  const list = [];
  const logoOk = (file) => file && ((state.logos.includes(file) && !state.deletions.has(file)) || state.uploads[file]);
  const shown = (entry) => entryFiles(entry).every(logoOk);
  const needs = (entry) => (entry.wordmark ? "light and dark wordmarks" : "a logo");
  if (!countedRepos().length) list.push("Chart coverage needs at least one repository.");
  const banner = c.banner?.file;
  if (!banner || !(state.banners.includes(banner) || state.bannerUploads[banner])) list.push("Banner: choose or upload a photo.");
  (c.projects || []).forEach((p) => {
    const where = p.name || p.repository;
    if (!p.name?.trim()) list.push(`Watchlist: ${p.repository} needs a name.`);
    if (!/^[A-Z0-9]{1,6}$/.test(p.ticker || "")) list.push(`Watchlist: ${where} needs a ticker of 1 to 6 letters or digits.`);
    if (!shown(p)) list.push(`Watchlist: ${where} needs ${needs(p)}.`);
  });
  (c.collaborations || []).forEach((e) => {
    if (!e.name?.trim()) list.push(`Collaborations: ${e.repository} needs a name.`);
    if (!shown(e)) list.push(`Collaborations: ${e.name || e.repository} needs ${needs(e)}.`);
  });
  (c.achievements || []).forEach((a, i) => {
    const where = a.event || `achievement ${i + 1}`;
    for (const key of ["rank", "event", "tag"]) if (!a[key]?.trim()) list.push(`Track record: ${where} needs a ${key}.`);
    if (!/^https:\/\/[^\s]+$/.test(a.url || "")) list.push(`Track record: ${where} needs a link starting with https://.`);
    if (!logoOk(a.logo)) list.push(`Track record: ${where} needs a logo.`);
  });
  return list;
}

/**
 * Saves profile.json, new logos and logo deletions as one commit on main, fast-forward only.
 * Refuses if profile.json changed on GitHub since it was loaded. Reloads the board afterwards.
 */
export async function commit() {
  const files = [{ path: "profile.json", content: toBase64(utf8(formatConfig(state.config))) },
    ...Object.values(state.uploads).map((u) => ({ path: `assets/logos/${u.name}`, content: u.base64 })),
    ...Object.values(state.bannerUploads).filter((u) => u.name === state.config.banner?.file)
      .map((u) => ({ path: `assets/banners/${u.name}`, content: u.base64 }))];
  if (!files.every((f) => WRITABLE.some((rule) => rule.test(f.path)))) throw new Error("Refusing to write outside profile.json and assets/logos.");
  const usage = logoUsage();
  const removals = [...state.deletions];
  if (removals.some((name) => !DELETABLE.test(name) || deleteBlocker(name, usage))) throw new Error("Refusing to delete a logo that is still in use");
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
  for (const name of removals) tree.push({ path: `assets/logos/${name}`, mode: "100644", type: "blob", sha: null });
  const newTree = await api(`${repo}/git/trees`, { method: "POST", body: { base_tree: base, tree } });
  const made = await api(`${repo}/git/commits`, { method: "POST",
    body: { message: "Update the profile board from the dashboard", tree: newTree.sha, parents: [head] } });
  await api(`${repo}/git/refs/heads/${BRANCH}`, { method: "PATCH", body: { sha: made.sha, force: false } });
  await load();
}
