// GitHub REST client. The token, when present, is sent only to api.github.com.

import { API, OWNER, REPO } from "./config.js";
import { state } from "./state.js";

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (body) headers["Content-Type"] = "application/json";
  const response = await fetch(API + path, { method, headers, body: body && JSON.stringify(body), cache: "no-store",
    credentials: "omit", referrerPolicy: "no-referrer" });
  if (!response.ok) {
    let message = response.statusText;
    try { message = (await response.json()).message || message; } catch { /* keep status text */ }
    throw new ApiError(response.status, message);
  }
  return response.status === 204 ? null : response.json();
}

/** The owner's public repositories, newest push first, excluding this profile repository. */
export async function ownedRepos() {
  const repos = [];
  for (let page = 1; page < 10; page++) {
    const batch = await api(`/users/${OWNER}/repos?type=owner&per_page=100&page=${page}`);
    repos.push(...batch);
    if (batch.length < 100) break;
  }
  return repos.filter((repo) => !repo.private && repo.full_name.toLowerCase() !== `${OWNER}/${REPO}`.toLowerCase())
    .sort((a, b) => b.pushed_at.localeCompare(a.pushed_at));
}
