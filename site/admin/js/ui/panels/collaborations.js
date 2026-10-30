// Collaborations: other people's projects that merged the owner's pull requests.

import { h } from "../../lib/dom.js";
import { state } from "../../state.js";
import { checklist, filterBox, shownAs, sortableItem, textField } from "../controls.js";
import { entryDisc, logoSelect, wordmarkSelects } from "../logo-picker.js";

const sameRepo = (a, b) => a.toLowerCase() === b.toLowerCase();

export function choices() {
  const collabs = state.config.collaborations ||= [];
  return checklist(state.external,
    (repo) => collabs.some((e) => sameRepo(e.repository, repo.name)),
    (repo, on) => {
      if (on) collabs.push({ repository: repo.name, name: repo.name.split("/").pop(), logo: "" });
      else collabs.splice(collabs.findIndex((e) => sameRepo(e.repository, repo.name)), 1);
    },
    (repo) => ({ title: repo.name, sub: [repo.merged_prs ? `${repo.merged_prs} merged PRs` : "", repo.language,
      repo.stars ? `★ ${repo.stars}` : ""].filter(Boolean).join(" · ") }));
}

export function panel() {
  const collabs = state.config.collaborations ||= [];
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Collaborations"),
      h("p", {}, "Other people's projects that merged your pull requests. A wordmark replaces the logo and the name.")),
    h("div", { class: "columns" },
      h("div", {}, h("h3", {}, `On the board (${collabs.length})`),
        collabs.length ? h("ol", { class: "sortable" }, collabs.map((e, i) => sortableItem(collabs, i, [
          entryDisc(e, "cover"),
          h("div", { class: "fields" },
            textField("Name", e.name, (v) => { e.name = v; }),
            shownAs(e),
            e.wordmark ? wordmarkSelects(e, e.name) : logoSelect(e.logo, e.repository.split("/").pop(), (f) => { e.logo = f; }),
            h("p", { class: "meta" }, e.repository)),
        ]))) : h("p", { class: "empty-state" }, "Pick projects you have contributed to.")),
      h("div", {}, h("h3", {}, "Repositories with your merged pull requests"), filterBox(), choices())),
  ];
}
