// Draws the page from the store: the tape, the sign-in card, the tabs, the active panel and the
// save bar. startUi() wires the redraw hooks and draws the first frame.

import { changedSections, commit, discard, isDirty, load, problems } from "../board.js";
import { OWNER, REPO, TABS } from "../config.js";
import { $, h, toast } from "../lib/dom.js";
import { state } from "../state.js";
import { ui } from "./hooks.js";
import { PANELS } from "./panels/index.js";
import { renderSignIn } from "./sign-in.js";

function renderTape() {
  const changed = new Set(changedSections());
  const c = state.config;
  $("#tape").replaceChildren(...[["WATCHLIST", c.projects, "Watchlist"], ["COLLAB", c.collaborations, "Collaborations"],
    ["COVERAGE", c.activity_repositories, "Chart coverage"], ["AWARDS", c.achievements, "Track record"]].map(([label, list, section]) =>
    h("span", { class: changed.has(section) ? "changed" : null }, h("b", {}, label), (list || []).length, changed.has(section) ? " ▲ edited" : "")));
}

function renderTabs() {
  const counts = { watchlist: state.config.projects, collabs: state.config.collaborations,
    coverage: state.config.activity_repositories, record: state.config.achievements, logos: state.logos };
  $("#tabs").replaceChildren(...TABS.map(([tab, label]) => h("button", { type: "button", role: "tab", "aria-selected": String(state.tab === tab),
    onclick: () => { state.tab = tab; state.filter = ""; renderTabs(); renderPanel(); } },
  label, h("span", { class: "count" }, (counts[tab] || []).length))));
}

function renderPanel() {
  $("#panel").replaceChildren(...PANELS[state.tab].panel());
}

function renderFooter() {
  const changes = changedSections();
  const uploads = Object.keys(state.uploads).length;
  const removed = state.deletions.size;
  const dirty = isDirty();
  const issues = dirty ? problems() : [];
  const summary = dirty ? `Unsaved: ${[...changes, uploads ? `${uploads} new logo${uploads > 1 ? "s" : ""}` : "",
    removed ? `${removed} logo${removed > 1 ? "s" : ""} deleted` : ""].filter(Boolean).join(", ")}`
    : "No unsaved changes";
  const canSave = dirty && !issues.length && state.user && !state.saving;
  $("#footer").replaceChildren(h("div", { class: "inner" },
    h("div", {}, h("strong", {}, summary), issues.length ? h("ul", { class: "error" }, issues.slice(0, 4).map((i) => h("li", {}, i))) : null),
    h("div", { class: "buttons" },
      h("button", { class: "btn", type: "button", disabled: !dirty || state.saving, onclick: () => { discard(); renderAll(); } }, "Discard"),
      h("button", { class: "btn primary", type: "button", disabled: !canSave, onclick: save }, state.saving ? "Saving…" : "Save to profile"))));
}

async function save() {
  if (problems().length || !state.user) return;
  state.saving = true;
  renderFooter();
  try {
    await commit();
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

/** Loads the board once signed in; keeps unsaved edits across a lock and sign-in. */
async function openEditor() {
  try {
    if (!state.config) await load();
  } catch (error) {
    toast(`Couldn't load the profile settings: ${error.message}.`);
  }
  renderAll();
}

function renderAll() {
  renderSignIn(openEditor);
  const open = Boolean(state.user && state.config);
  for (const id of ["#tape", "#tabs", "#panel", "#footer"]) $(id).hidden = !open;
  if (!open) return;
  renderTape();
  renderTabs();
  renderPanel();
  renderFooter();
}

export function startUi() {
  Object.assign(ui, {
    all: renderAll,
    panel: renderPanel,
    edited: () => { renderTape(); renderFooter(); },
    picker: () => PANELS[state.tab].choices?.() ?? null,
  });
  renderAll();
}
