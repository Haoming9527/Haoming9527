// Shared form pieces: text fields, drag-to-reorder rows, filterable checklists and the
// logo/wordmark switch.

import { $, h } from "../lib/dom.js";
import { since } from "../lib/format.js";
import { state } from "../state.js";
import { redraw, ui } from "./hooks.js";

export function textField(label, value, onInput, attrs = {}) {
  return h("label", { class: attrs.class || (attrs.wide ? "wide" : null) }, label,
    h("input", { type: attrs.type || "text", value: value || "", maxlength: attrs.maxlength || 120, placeholder: attrs.placeholder,
      autocomplete: "off", spellcheck: attrs.spellcheck ?? "true",
      oninput: (event) => { onInput(event.target.value); ui.edited(); } }));
}

function move(list, from, to) {
  if (to < 0 || to >= list.length || from === to) return;
  list.splice(to, 0, list.splice(from, 1)[0]);
  redraw();
}

export function sortableItem(list, index, children) {
  const item = h("li", { class: "item" },
    h("span", { class: "handle", draggable: "true", title: "Drag to reorder", "aria-hidden": "true",
      ondragstart: (event) => { event.dataTransfer.setData("text/plain", String(index)); event.dataTransfer.setDragImage(item, 24, 24); } },
    "⠿"),
    children,
    h("div", { class: "actions" },
      h("button", { class: "icon", type: "button", "aria-label": "Move up", title: "Move up", onclick: () => move(list, index, index - 1) }, "▲"),
      h("button", { class: "icon", type: "button", "aria-label": "Move down", title: "Move down", onclick: () => move(list, index, index + 1) }, "▼"),
      h("button", { class: "icon", type: "button", "aria-label": "Remove", title: "Remove",
        onclick: () => { list.splice(index, 1); redraw(); } }, "✕")));
  item.addEventListener("dragover", (event) => { event.preventDefault(); item.classList.add("drop"); });
  item.addEventListener("dragleave", () => item.classList.remove("drop"));
  item.addEventListener("drop", (event) => {
    event.preventDefault();
    item.classList.remove("drop");
    move(list, Number(event.dataTransfer.getData("text/plain")), index);
  });
  return item;
}

export function checklist(items, isOn, toggle, describe, lockedReason) {
  const query = state.filter.toLowerCase();
  const shown = items.filter((item) => describe(item).title.toLowerCase().includes(query));
  return h("ul", { class: "picker" }, shown.length ? shown.map((item) => {
    const { title, sub } = describe(item);
    const locked = lockedReason?.(item);
    return h("li", {}, h("label", { title: locked || null },
      h("input", { type: "checkbox", checked: isOn(item), disabled: Boolean(locked),
        onchange: (event) => { toggle(item, event.target.checked); redraw(); } }),
      h("span", {}, h("span", { class: "name" }, title), h("span", { class: "sub" }, locked || sub))));
  }) : h("li", { class: "hint" }, "Nothing matches that filter."));
}

export function filterBox() {
  return h("input", { type: "search", placeholder: "Filter repositories", value: state.filter, "aria-label": "Filter repositories",
    oninput: (event) => {
      state.filter = event.target.value;
      const list = $("#panel .picker");
      const next = ui.picker();
      if (list && next) list.replaceWith(next);
    } });
}

export const repoLine = (repo) => [repo.language, repo.stargazers_count ? `★ ${repo.stargazers_count}` : "",
  state.commits[repo.full_name.toLowerCase()] ? `${state.commits[repo.full_name.toLowerCase()]} commits` : "", `pushed ${since(repo.pushed_at)}`,
  repo.fork ? "fork" : "", repo.archived ? "archived" : ""].filter(Boolean).join(" · ");

/** "Logo + name" or "Wordmark" for a watchlist or collaboration entry. */
export function shownAs(entry) {
  return h("label", {}, "Shown as", h("select", {
    onchange: (event) => {
      if (event.target.value === "wordmark") { delete entry.logo; delete entry.logo_fit; entry.wordmark = { light: "", dark: "" }; }
      else { delete entry.wordmark; entry.logo = ""; }
      redraw();
    } },
  h("option", { value: "logo", selected: !entry.wordmark }, "Logo + name"),
  h("option", { value: "wordmark", selected: Boolean(entry.wordmark) }, "Wordmark")));
}
