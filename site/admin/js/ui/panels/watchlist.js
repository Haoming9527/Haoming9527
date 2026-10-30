// Watchlist: the owner's projects, shown as rows with a chart line.

import { ensureCoverage } from "../../board.js";
import { h } from "../../lib/dom.js";
import { prettyName, suggestTicker } from "../../lib/format.js";
import { state } from "../../state.js";
import { checklist, filterBox, repoLine, shownAs, sortableItem, textField } from "../controls.js";
import { redraw } from "../hooks.js";
import { entryDisc, logoSelect, wordmarkSelects } from "../logo-picker.js";

const sameRepo = (a, b) => a.toLowerCase() === b.toLowerCase();

export function choices() {
  const projects = state.config.projects ||= [];
  return checklist(state.repos,
    (repo) => projects.some((p) => sameRepo(p.repository, repo.full_name)),
    (repo, on) => {
      if (on) {
        const name = prettyName(repo.full_name);
        projects.push({ repository: repo.full_name, name, ticker: suggestTicker(name), logo: "" });
        ensureCoverage(repo.full_name);
      } else {
        projects.splice(projects.findIndex((p) => sameRepo(p.repository, repo.full_name)), 1);
      }
    },
    (repo) => ({ title: repo.name, sub: repoLine(repo) }));
}

function logoFields(p) {
  const base = p.repository.split("/").pop();
  if (p.wordmark) return wordmarkSelects(p, base);
  return [
    logoSelect(p.logo, base, (file) => { p.logo = file; }),
    h("label", {}, "Logo fit", h("select", { onchange: (e) => { if (e.target.value === "cover") delete p.logo_fit; else p.logo_fit = "contain"; redraw(); } },
      h("option", { value: "cover", selected: p.logo_fit !== "contain" }, "Fill the circle"),
      h("option", { value: "contain", selected: p.logo_fit === "contain" }, "Fit inside"))),
  ];
}

export function panel() {
  const projects = state.config.projects ||= [];
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Watchlist"),
      h("p", {}, "Projects shown as rows with a chart line. Drag to reorder; adding one also adds it to chart coverage.")),
    h("div", { class: "columns" },
      h("div", {}, h("h3", {}, `On the board (${projects.length})`),
        projects.length ? h("ol", { class: "sortable" }, projects.map((p, i) => sortableItem(projects, i, [
          entryDisc(p, p.logo_fit === "contain" ? "" : "cover"),
          h("div", { class: "fields" },
            textField("Name", p.name, (v) => { p.name = v; }),
            textField("Ticker", p.ticker, (v) => { p.ticker = v.toUpperCase().replace(/[^A-Z0-9]/g, ""); }, { maxlength: 6, spellcheck: "false" }),
            shownAs(p),
            logoFields(p),
            h("p", { class: "meta" }, p.repository)),
        ]))) : h("p", { class: "empty-state" }, "Pick projects from your repositories.")),
      h("div", {}, h("h3", {}, "Your public repositories"), filterBox(), choices())),
  ];
}
