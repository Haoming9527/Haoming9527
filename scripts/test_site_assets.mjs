import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { API, OWNER, RAW, REPO } from "../site/admin/js/config.js";
import { commit, deleteBlocker, isDirty, load, problems } from "../site/admin/js/board.js";
import { state } from "../site/admin/js/state.js";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const prefix = `/repos/${OWNER}/${REPO}`;
const png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC";
const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>';
const upload = (name, content = png) => ({ name, base64: content });
const initialConfig = () => ({
  github_username: OWNER, display_name: "Economist", role: "Engineer", portfolio: "https://example.com/", utc_offset_hours: 8,
  projects: [{ repository: `${OWNER}/app`, name: "App", ticker: "APP", logo: "project.png" }],
  collaborations: [{ repository: "team/project", name: "Team project", logo: "collaboration.png" }],
  achievements: [{ rank: "Winner", event: "Event", tag: "App", logo: "achievement.png", url: "https://example.com/event" }],
  banner: { file: "banner.png", alt: "Original banner" }, activity_exclusions: [],
  star_collaborator_repositories: ["team/project"], star_access_verified_at: "2026-11-22T00:00:00Z",
});
const response = (body, status = 200) => ({ ok: status < 400, status, statusText: "Test response",
  json: async () => body, text: async () => typeof body === "string" ? body : JSON.stringify(body) });

/** A Git object store: files become public only when the branch ref is updated. */
function backend({ catalogKnown = true, rejectRef = false } = {}) {
  state.token = "test-only-token";
  state.user = OWNER;
  let published = new Map([
    ["profile.json", Buffer.from(JSON.stringify(initialConfig())).toString("base64")],
    ...["project.png", "collaboration.png", "achievement.png", "unused.png"].map(name => [`assets/logos/${name}`, png]),
    ["assets/logos/react.svg", Buffer.from(svg).toString("base64")], ["assets/banners/banner.png", png],
  ]);
  const blobs = new Map();
  const trees = new Map();
  const commits = new Map();
  const calls = [];
  let head = "base-head", configSha = "config-sha";
  globalThis.fetch = async (url, options = {}) => {
    const path = String(url).replace(API, "");
    const method = options.method || "GET";
    const body = options.body ? JSON.parse(options.body) : undefined;
    calls.push({ path, method, body });
    if (path === "/user") return response({ login: OWNER });
    if (path.startsWith("/user/repos?")) return response([
      { full_name: "team/project", private: false, permissions: { push: true } },
    ]);
    if (path.startsWith(`/users/${OWNER}/repos?`)) return response([
      { full_name: `${OWNER}/app`, private: false, fork: false, pushed_at: "2026-11-22T00:00:00Z" },
    ]);
    if (String(url) === `${RAW}/market/data/activity.json`) return response({}, 404);
    if (String(url) === `${RAW}/main/scripts/catalog.py`) return response(
      catalogKnown ? 'VENDORED = {\n"React": ("react.svg", .6),\n}' : "", catalogKnown ? 200 : 404);
    if (path.startsWith(`${prefix}/contents/profile.json?`)) return response({ sha: configSha, content: published.get("profile.json") });
    for (const directory of ["logos", "banners"]) {
      if (path.startsWith(`${prefix}/contents/assets/${directory}?`)) return response([...published.keys()]
        .filter(name => name.startsWith(`assets/${directory}/`)).map(name => ({ type: "file", name: name.split("/").pop() })));
    }
    if (path === `${prefix}/git/ref/heads/main`) return response({ object: { sha: head } });
    if (path === `${prefix}/git/commits/${head}` && method === "GET") return response({ tree: { sha: "base-tree" } });
    if (path === `${prefix}/git/blobs` && method === "POST") {
      assert.equal(body.encoding, "base64");
      const sha = `blob-${blobs.size}`;
      blobs.set(sha, body.content);
      return response({ sha });
    }
    if (path === `${prefix}/git/trees` && method === "POST") {
      assert.equal(body.base_tree, "base-tree");
      const next = new Map(published);
      for (const item of body.tree) {
        if (item.sha === null) next.delete(item.path);
        else { assert(blobs.has(item.sha)); next.set(item.path, blobs.get(item.sha)); }
      }
      trees.set("new-tree", next);
      return response({ sha: "new-tree" });
    }
    if (path === `${prefix}/git/commits` && method === "POST") {
      assert.deepEqual(body.parents, [head]);
      commits.set("new-commit", trees.get(body.tree));
      return response({ sha: "new-commit" });
    }
    if (path === `${prefix}/git/refs/heads/main` && method === "PATCH") {
      assert.equal(body.force, false);
      if (rejectRef) return response({ message: "Reference update failed" }, 422);
      published = commits.get(body.sha);
      head = body.sha;
      configSha = "new-config-sha";
      return response({});
    }
    throw new Error(`Unexpected request ${method} ${path}`);
  };
  return {
    calls, files: () => published, config: () => JSON.parse(Buffer.from(published.get("profile.json"), "base64")),
    writes: () => calls.filter(call => call.method !== "GET"),
    changeConfigSha() { configSha = "concurrent-config-sha"; },
  };
}

test("replacing a logo and deleting its unused predecessor publishes one complete commit", async () => {
  const server = backend();
  await load();
  state.uploads["replacement.png"] = upload("replacement.png");
  state.config.projects[0].logo = "replacement.png";
  state.deletions.add("project.png");
  assert.equal(deleteBlocker("project.png"), "");
  assert.deepEqual(problems(), []);
  await commit();
  assert.equal(server.config().projects[0].logo, "replacement.png");
  assert.equal(server.files().get("assets/logos/replacement.png"), png);
  assert(!server.files().has("assets/logos/project.png"));
  assert.equal(server.writes().filter(call => call.method === "PATCH").length, 1);
  assert.equal(server.writes().at(-1).method, "PATCH");
  assert.equal(isDirty(), false);
});

test("SVG light and dark wordmarks are saved together with the selected presentation", async () => {
  const server = backend();
  await load();
  const entry = state.config.collaborations[0];
  delete entry.logo;
  entry.wordmark = { light: "wordmark-light.svg", dark: "wordmark-dark.svg" };
  for (const [theme, name] of Object.entries(entry.wordmark)) {
    state.uploads[name] = upload(name, Buffer.from(svg.replace("<path", `<path fill="${theme === "light" ? "black" : "white"}"`)).toString("base64"));
  }
  state.deletions.add("collaboration.png");
  await commit();
  assert.deepEqual(server.config().collaborations[0].wordmark, entry.wordmark);
  assert(server.files().has("assets/logos/wordmark-light.svg"));
  assert(server.files().has("assets/logos/wordmark-dark.svg"));
  assert.notEqual(server.files().get("assets/logos/wordmark-light.svg"), server.files().get("assets/logos/wordmark-dark.svg"));
  assert(!server.files().has("assets/logos/collaboration.png"));
});

test("only the chosen banner upload is published with its updated description", async () => {
  const server = backend();
  await load();
  state.bannerUploads["chosen.png"] = upload("chosen.png");
  state.bannerUploads["discarded.png"] = upload("discarded.png");
  state.config.banner = { file: "chosen.png", alt: 'A new banner & "description"' };
  await commit();
  assert.deepEqual(server.config().banner, { file: "chosen.png", alt: 'A new banner & "description"' });
  assert(server.files().has("assets/banners/chosen.png"));
  assert(!server.files().has("assets/banners/discarded.png"));
});

test("removing all optional sections allows deletion of their unused logos", async () => {
  const server = backend();
  await load();
  state.config.projects = [];
  state.config.collaborations = [];
  state.config.achievements = [];
  state.deletions = new Set(["project.png", "collaboration.png", "achievement.png"]);
  assert.deepEqual(problems(), []);
  await commit();
  for (const section of ["projects", "collaborations", "achievements"]) assert.deepEqual(server.config()[section], []);
  for (const name of ["project.png", "collaboration.png", "achievement.png"]) assert(!server.files().has(`assets/logos/${name}`));
  assert(server.files().has("assets/logos/react.svg"));
});

test("text and achievement edits preserve their values through the saved JSON", async () => {
  const server = backend();
  await load();
  state.config.projects[0].name = '新项目 & "App"';
  state.config.achievements[0] = { ...state.config.achievements[0], rank: "Top 3", event: "New event", tag: "NEW", url: "https://example.com/new" };
  const expected = structuredClone(state.config);
  await commit();
  assert.deepEqual(server.config().projects, expected.projects);
  assert.deepEqual(server.config().achievements, expected.achievements);
});

test("a still-used logo cannot be deleted before any Git objects are written", async () => {
  const server = backend();
  await load();
  state.deletions.add("project.png");
  assert.match(deleteBlocker("project.png"), /Used by App/);
  await assert.rejects(commit(), /needs a logo/);
  assert.deepEqual(server.writes(), []);
});

test("language and tool logos cannot be deleted", async () => {
  const server = backend();
  await load();
  state.deletions.add("react.svg");
  assert.match(deleteBlocker("react.svg"), /language or tool/);
  await assert.rejects(commit(), /Refusing to delete/);
  assert.deepEqual(server.writes(), []);
});

test("deletion stays blocked when the protected catalog could not be loaded", async () => {
  const server = backend({ catalogKnown: false });
  await load();
  state.deletions.add("unused.png");
  assert.match(deleteBlocker("unused.png"), /couldn't be read/);
  await assert.rejects(commit(), /Refusing to delete/);
  assert.deepEqual(server.writes(), []);
});

test("missing logo, incomplete wordmarks, and missing banner prevent any writes", async (t) => {
  for (const kind of ["logo", "wordmark", "banner"]) await t.test(kind, async () => {
    const server = backend();
    await load();
    if (kind === "logo") state.config.achievements[0].logo = "missing.png";
    if (kind === "wordmark") state.config.projects[0].wordmark = { light: "project.png" };
    if (kind === "banner") state.config.banner.file = "missing.png";
    assert(problems().length);
    await assert.rejects(commit(), /needs|choose or upload/);
    assert.deepEqual(server.writes(), []);
  });
});

test("a concurrent profile update stops saving before any write", async () => {
  const server = backend();
  await load();
  state.config.projects[0].name = "Changed locally";
  server.changeConfigSha();
  await assert.rejects(commit(), /changed on GitHub/);
  assert.deepEqual(server.writes(), []);
  assert.equal(server.config().projects[0].name, "App");
});

test("a rejected branch update leaves the published config and assets intact", async () => {
  const server = backend({ rejectRef: true });
  await load();
  const before = new Map(server.files());
  state.config.projects[0].logo = "replacement.png";
  state.uploads["replacement.png"] = upload("replacement.png");
  state.deletions.add("project.png");
  await assert.rejects(commit(), /Reference update failed/);
  assert.deepEqual(server.files(), before);
  assert.equal(isDirty(), true);
});
