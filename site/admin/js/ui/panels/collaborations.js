// Collaborations: public projects where the owner has verified collaborator access.

import { h } from "../../lib/dom.js";
import { state } from "../../state.js";
import { checklist, filterBox, shownAs, sortableItem, textField } from "../controls.js";
import { entryDisc, logoSelect, wordmarkSelects } from "../logo-picker.js";

const sameRepo = (a, b) => a.toLowerCase() === b.toLowerCase();

export function choices() {
  const collabs = state.config.collaborations ||= [];
  if (!state.external.length) return h("ul", { class: "picker" },
    h("li", { class: "hint" }, "No public projects with collaborator access were found for this account."));
  return checklist(state.external,
    (repo) => collabs.some((e) => sameRepo(e.repository, repo.name)),
    (repo, on) => {
      if (on) collabs.push({ repository: repo.name, name: repo.name.split("/").pop(), logo: "" });
      else collabs.splice(collabs.findIndex((e) => sameRepo(e.repository, repo.name)), 1);
    },
    (repo) => ({ title: repo.name, sub: [repo.merged_prs ? `${repo.merged_prs} merged PR${repo.merged_prs === 1 ? "" : "s"}` : "", repo.language,
      repo.stars ? `★ ${repo.stars}` : ""].filter(Boolean).join(" · ") }));
}

export function panel() {
  const collabs = state.config.collaborations ||= [];
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Collaborations"),
      h("p", {}, "Public projects where you have collaborator access. All count in Stars; your selections control the rows shown here. Merged PRs still counts all your public merged pull requests. A wordmark replaces the logo and the name.")),
    h("div", { class: "columns" },
      h("div", {}, h("h3", {}, `On the board (${collabs.length})`),
        collabs.length ? h("ol", { class: "sortable" }, collabs.map((e, i) => sortableItem(collabs, i, [
          entryDisc(e, "cover"),
          h("div", { class: "fields" },
            textField("Name", e.name, (v) => { e.name = v; }),
            shownAs(e),
            e.wordmark ? wordmarkSelects(e, e.name) : logoSelect(e.logo, e.repository.split("/").pop(), (f) => { e.logo = f; }),
            h("p", { class: "meta" }, e.repository),
            state.external.some((repo) => sameRepo(repo.name, e.repository)) ? null
              : h("p", { class: "error" }, "Collaborator access is no longer verified. Remove this project before saving.")),
        ]))) : h("p", { class: "empty-state" }, "Pick projects where you have collaborator access.")),
      h("div", {}, h("h3", {}, "Projects with collaborator access"),
        state.snapshotMissing ? h("p", { class: "hint error" },
          "PR counts are unavailable. The projects below still have verified collaborator access.") : null,
        filterBox(), choices())),
  ];
}
