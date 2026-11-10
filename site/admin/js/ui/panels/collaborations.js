// Collaborations: public projects where the owner has verified collaborator access.

import { restrictCollaborations } from "../../board.js";
import { h } from "../../lib/dom.js";
import { state } from "../../state.js";
import { checklist, filterBox, shownAs, sortableItem, textField } from "../controls.js";
import { entryDisc, logoSelect, wordmarkSelects } from "../logo-picker.js";

const sameRepo = (a, b) => a.toLowerCase() === b.toLowerCase();

export function choices() {
  const collabs = restrictCollaborations();
  if (!state.external.length) return h("ul", { class: "picker" },
    h("li", { class: "hint" }, "No public projects with collaborator access were found for this account."));
  return checklist(state.external,
    (repo) => collabs.some((e) => sameRepo(e.repository, repo.name)),
    (repo, on) => {
      if (on) collabs.push({ repository: repo.name, name: repo.name.split("/").pop(), logo: "" });
      else {
        const at = collabs.findIndex((e) => sameRepo(e.repository, repo.name));
        if (at >= 0) collabs.splice(at, 1);
      }
    },
    (repo) => ({ title: repo.name }));
}

export function panel() {
  const collabs = restrictCollaborations();
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Collaborations"),
      h("p", {}, "Repositories where you have collaborator access.")),
    h("div", { class: "columns" },
      h("div", {}, h("h3", {}, `On the board (${collabs.length})`),
        collabs.length ? h("ol", { class: "sortable" }, collabs.map((e, i) => sortableItem(collabs, i, [
          entryDisc(e, "cover"),
          h("div", { class: "fields" },
            textField("Name", e.name, (v) => { e.name = v; }),
            shownAs(e),
            e.wordmark ? wordmarkSelects(e, e.name) : logoSelect(e.logo, e.repository.split("/").pop(), (f) => { e.logo = f; }),
            h("p", { class: "meta" }, e.repository)),
        ]))) : h("p", { class: "empty-state" }, "Pick projects where you have collaborator access.")),
      h("div", {}, h("h3", {}, "Projects with collaborator access"),
        filterBox(), choices())),
  ];
}
