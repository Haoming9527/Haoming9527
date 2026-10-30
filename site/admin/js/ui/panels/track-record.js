// Track record: achievement tiles, two per row.

import { h } from "../../lib/dom.js";
import { state } from "../../state.js";
import { sortableItem, textField } from "../controls.js";
import { redraw } from "../hooks.js";
import { disc, logoSelect } from "../logo-picker.js";

export function panel() {
  const record = state.config.achievements ||= [];
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Track record"),
      h("p", {}, "Achievement tiles, two per row. The tag shows on the tile; the link opens when someone clicks it.")),
    record.length ? h("ol", { class: "sortable" }, record.map((a, i) => sortableItem(record, i, [
      disc(a.logo, "square"),
      h("div", { class: "fields record" },
        textField("Result", a.rank, (v) => { a.rank = v; }, { placeholder: "Winner, Top 10…" }),
        textField("Event", a.event, (v) => { a.event = v; }, { placeholder: "Hackathon or award", class: "span-2" }),
        textField("Tag", a.tag, (v) => { a.tag = v; }, { placeholder: "Project or year", maxlength: 30 }),
        textField("Link", a.url, (v) => { a.url = v.trim(); }, { type: "url", placeholder: "https://", spellcheck: "false", maxlength: 300, class: "span-3" }),
        logoSelect(a.logo, a.event || "achievement", (f) => { a.logo = f; })),
    ]))) : h("p", { class: "empty-state" }, "No achievements yet."),
    h("div", { class: "toolbar" },
      h("button", { class: "btn", type: "button", onclick: () => { record.push({ rank: "", event: "", tag: "", logo: "", url: "" }); redraw(); } },
        "Add an achievement")),
  ];
}
