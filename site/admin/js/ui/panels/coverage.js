// Chart coverage: every public repository the owner has counts automatically, new ones included.
// Forks never count. Unticking a repository adds it to activity_exclusions.

import { countedRepos, isExcluded, setCounted } from "../../board.js";
import { h } from "../../lib/dom.js";
import { state } from "../../state.js";
import { filterBox, repoLine } from "../controls.js";
import { redraw } from "../hooks.js";

const watched = (name) => (state.config.projects || []).some((p) => p.repository.toLowerCase() === name.toLowerCase());
const lockReason = (repo) => (repo.fork ? "Forks don't count" : watched(repo.full_name) ? "On the watchlist, so it stays in the chart" : "");

export function choices() {
  return h("div", { class: "grid picker" }, state.repos.filter((r) => r.name.toLowerCase().includes(state.filter.toLowerCase())).map((repo) =>
    h("label", { title: lockReason(repo) || null },
      h("input", { type: "checkbox", checked: !repo.fork && !isExcluded(repo.full_name), disabled: Boolean(lockReason(repo)),
        onchange: (event) => { setCounted(repo.full_name, event.target.checked); redraw(); } }),
      h("span", {}, h("span", { class: "name" }, repo.name),
        h("span", { class: "sub" }, lockReason(repo) || repoLine(repo))))));
}

export function panel() {
  const exclusions = state.config.activity_exclusions ||= [];
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Chart coverage"),
      h("p", {}, "Every public repository you own feeds the candles, the indexes, languages and the tech stack, new ones included. Forks don't count. Untick a repository to leave it out.")),
    h("div", { class: "toolbar" }, filterBox(),
      h("button", { class: "btn small", type: "button", disabled: !exclusions.length, onclick: () => { exclusions.length = 0; redraw(); } }, "Count all"),
      h("span", { class: "hint" }, `${countedRepos().length} of ${state.repos.filter((r) => !r.fork).length} counted`)),
    choices(),
  ];
}
