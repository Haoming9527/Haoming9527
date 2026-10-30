// Logos: every file in assets/logos. A file can be deleted only when nothing on the board uses it.

import { deleteBlocker, logoUsage } from "../../board.js";
import { h } from "../../lib/dom.js";
import { state } from "../../state.js";
import { redraw } from "../hooks.js";
import { disc, libraryFiles } from "../logo-picker.js";

function row(file, usage) {
  const deleted = state.deletions.has(file);
  const reason = deleteBlocker(file, usage);
  const status = deleted ? "Will be deleted when you save" : reason || (state.uploads[file] ? "New, not saved yet" : "Not used");
  const button = deleted
    ? h("button", { class: "btn small", type: "button", onclick: () => { state.deletions.delete(file); redraw(); } }, "Undo")
    : h("button", { class: "btn small danger", type: "button", disabled: Boolean(reason), title: reason || "Delete this logo",
      onclick: () => { if (state.uploads[file]) delete state.uploads[file]; else state.deletions.add(file); redraw(); } },
    "Delete");
  return h("li", { class: "logo-row" }, disc(file, /\.png$/i.test(file) ? "cover" : ""),
    h("span", {}, h("span", { class: "name" }, file), h("span", { class: "sub" }, status)),
    button);
}

export function panel() {
  const usage = logoUsage();
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Logos"),
      h("p", {}, "Files in assets/logos. A logo can be deleted only when nothing on the board uses it.")),
    h("ul", { class: "picker logos" }, libraryFiles({ includeDeleted: true }).map((file) => row(file, usage))),
  ];
}
