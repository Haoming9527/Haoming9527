import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { API, OWNER, RAW, REPO } from "../site/admin/js/config.js";
import { collaboratorRepos } from "../site/admin/js/github.js";
import { changedSections, commit, discard, isDirty, load, problems } from "../site/admin/js/board.js";
import { state } from "../site/admin/js/state.js";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

const repo = (full_name, permissions = { push: true }, extra = {}) => ({
  full_name, private: false, visibility: "public", permissions, stargazers_count: 12, language: "JavaScript", ...extra,
});
const response = (body, ok = true) => ({ ok, status: ok ? 200 : 404,
  json: async () => body, text: async () => typeof body === "string" ? body : JSON.stringify(body) });
const config = (access = [], selected = []) => ({ github_username: OWNER, projects: [], activity_exclusions: [],
  collaborations: selected.map((repository) => ({ repository, name: repository.split("/")[1], logo: "logo.png" })),
  achievements: [], banner: { file: "nyse.png" }, star_collaborator_repositories: access,
  star_access_verified_at: "2026-10-30T00:00:00Z" });

function session() {
  state.token = "secret-local-token";
  state.user = OWNER;
}

function backend({ accessible = [], initial = config(), snapshot = null } = {}) {
  session();
  let stored = structuredClone(initial);
  const calls = [];
  const written = [];
  globalThis.fetch = async (url, options = {}) => {
    const path = String(url).replace(API, "");
    const method = options.method || "GET";
    calls.push({ path, method });
    if (path === "/user") return response({ login: OWNER });
    if (path.startsWith("/user/repos?")) return response(accessible);
    if (path.startsWith(`/users/${OWNER}/repos?`)) return response([
      repo(`${OWNER}/app`, { admin: true }, { pushed_at: "2026-11-10T00:00:00Z" }),
    ]);
    if (path.includes("/contents/profile.json?")) return response({ sha: "config-sha", content: Buffer.from(JSON.stringify(stored)).toString("base64") });
    if (path.includes("/contents/assets/logos?")) return response([{ type: "file", name: "logo.png" }]);
    if (path.includes("/contents/assets/banners?")) return response([{ type: "file", name: "nyse.png" }]);
    if (String(url) === `${RAW}/market/data/activity.json`) return response(snapshot, Boolean(snapshot));
    if (String(url) === `${RAW}/main/scripts/catalog.py`) return response('VENDORED = {\n"Logo": ("logo.png", 1),\n}');
    const prefix = `/repos/${OWNER}/${REPO}/git/`;
    if (path === `${prefix}ref/heads/main`) return response({ object: { sha: "head" } });
    if (path === `${prefix}commits/head`) return response({ tree: { sha: "base-tree" } });
    if (path === `${prefix}blobs`) {
      const body = JSON.parse(options.body);
      const value = Buffer.from(body.content, "base64").toString("utf8");
      written.push(value);
      stored = JSON.parse(value);
      return response({ sha: "new-blob" });
    }
    if (path === `${prefix}trees`) return response({ sha: "new-tree" });
    if (path === `${prefix}commits`) return response({ sha: "new-commit" });
    if (path === `${prefix}refs/heads/main`) return response({});
    throw new Error(`Unexpected test request ${path}`);
  };
  return { calls, written, setAccess(repos) { accessible = repos; } };
}

test("public write/maintain/admin projects count without PRs; private/read/triage/owned do not", async () => {
  session();
  globalThis.fetch = async (url) => String(url) === `${API}/user` ? response({ login: OWNER }) : response([
    repo("direct/no-pr"), repo("team/maintained", { maintain: true }), repo("team/admin", { admin: true }),
    repo("other/read", { pull: true }), repo("other/triage", { triage: true }),
    repo("other/private", { push: true }, { private: true }), repo("other/internal", { push: true }, { visibility: "internal" }),
    repo(`${OWNER}/own`), repo("other/unverified", { push: "true" }),
  ]);
  assert.deepEqual((await collaboratorRepos()).map((row) => row.full_name), ["direct/no-pr", "team/admin", "team/maintained"]);
});

test("access discovery follows every page and deduplicates names", async () => {
  session();
  const pages = [];
  globalThis.fetch = async (url) => {
    if (String(url) === `${API}/user`) return response({ login: OWNER });
    const params = new URL(url).searchParams;
    assert.equal(params.get("visibility"), "public");
    assert.equal(params.get("affiliation"), "collaborator,organization_member");
    const page = Number(params.get("page")); pages.push(page);
    return response(page === 1 ? Array.from({ length: 100 }, (_, i) => repo(`team/project-${i}`))
      : [repo("TEAM/PROJECT-0"), repo("team/last")]);
  };
  const rows = await collaboratorRepos();
  assert.deepEqual(pages, [1, 2]);
  assert.equal(rows.length, 101);
  assert(rows.some((row) => row.full_name === "team/last"));
});

test("a different authenticated account cannot replace the access list", async () => {
  session();
  let requests = 0;
  globalThis.fetch = async () => { requests++; return response({ login: "someone-else" }); };
  await assert.rejects(collaboratorRepos(), /Only Haoming9527/);
  assert.equal(requests, 1);
});

test("load never promotes snapshot PRs or stale configured projects into verified access", async () => {
  const initial = config(["direct/no-pr"], ["old/pr-only"]);
  backend({ accessible: [repo("direct/no-pr")], initial,
    snapshot: { open_source: { repositories: [{ name: "old/pr-only", merged_prs: 10 }] } } });
  await load();
  assert.deepEqual(state.external.map((row) => row.name), ["direct/no-pr"]);
  assert.equal(state.external[0].merged_prs, 0);
  assert.deepEqual(state.config, initial);
  assert.deepEqual(state.original, initial);
  assert.equal(isDirty(), false);
  assert(problems().some((problem) => problem.includes("old/pr-only") && problem.includes("access")));
});

test("missing snapshot retains verified access and never falls back to configured rows", async () => {
  backend({ accessible: [repo("team/active")], initial: config([], ["old/pr-only"]) });
  await load();
  assert.equal(state.snapshotMissing, true);
  assert.deepEqual(state.external.map((row) => row.name), ["team/active"]);
});

test("membership changes can be saved on their own; timestamps alone stay clean", async () => {
  const server = backend({ accessible: [repo("team/new")], initial: config(["team/old"]) });
  await load();
  assert.deepEqual(changedSections(), ["Collaborator access"]);
  assert.equal(isDirty(), true);
  await commit();
  const saved = JSON.parse(server.written[0]);
  assert.deepEqual(saved.star_collaborator_repositories, ["team/new"]);
  assert.match(saved.star_access_verified_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
  assert(!server.written[0].includes(state.token));
  assert.equal(isDirty(), false);
  assert.deepEqual(changedSections(), []);
});

test("discard can dismiss pending access sync without changing the original config", async () => {
  backend({ accessible: [repo("team/new")], initial: config(["team/old"]) });
  await load();
  assert.equal(isDirty(), true);
  discard();
  assert.equal(isDirty(), false);
  assert.deepEqual(state.config.star_collaborator_repositories, ["team/old"]);
});

test("save rechecks permissions and refuses stale selected projects before any write", async () => {
  const server = backend({ accessible: [repo("team/project")], initial: config(["team/project"], ["team/project"]) });
  await load();
  server.setAccess([]);
  await assert.rejects(commit(), /remove team\/project.*access/);
  assert.equal(server.written.length, 0);
  assert.equal(server.calls.filter((call) => call.method !== "GET").length, 0);
});
