// Chart coverage: repositories whose commits feed the candles, indexes, languages and stack.

import { h } from "../../lib/dom.js";
import { state } from "../../state.js";
import { filterBox, repoLine } from "../controls.js";
import { redraw } from "../hooks.js";

const sameRepo = (a, b) => a.toLowerCase() === b.toLowerCase();

export function choices() {
  const coverage = state.config.activity_repositories ||= [];
  const has = (name) => coverage.some((x) => sameRepo(x, name));
  const watched = (name) => (state.config.projects || []).some((p) => sameRepo(p.repository, name));
  return h("div", { class: "grid picker" }, state.repos.filter((r) => r.name.toLowerCase().includes(state.filter.toLowerCase())).map((repo) =>
    h("label", { title: watched(repo.full_name) ? "On the watchlist, so it stays in the chart" : null },
      h("input", { type: "checkbox", checked: has(repo.full_name), disabled: watched(repo.full_name),
        onchange: (event) => {
          if (event.target.checked) coverage.push(repo.full_name);
          else coverage.splice(coverage.findIndex((x) => sameRepo(x, repo.full_name)), 1);
          redraw();
        } }),
      h("span", {}, h("span", { class: "name" }, repo.name),
        h("span", { class: "sub" }, watched(repo.full_name) ? "On the watchlist" : repoLine(repo))))));
}

export function panel() {
  const coverage = state.config.activity_repositories ||= [];
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Chart coverage"),
      h("p", {}, "Repositories whose commits feed the candles, the commit index, languages and the tech stack.")),
    h("div", { class: "toolbar" }, filterBox(),
      h("button", { class: "btn small", type: "button", onclick: () => {
        for (const repo of state.repos) if (!coverage.some((x) => sameRepo(x, repo.full_name))) coverage.push(repo.full_name);
        redraw(); } }, "Select all"),
      h("span", { class: "hint" }, `${coverage.length} of ${state.repos.length} selected`)),
    choices(),
  ];
}
