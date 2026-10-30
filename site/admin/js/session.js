// The sign-in token: memory first, encrypted with a passphrase if remembered, locked after idling.

import { IDLE_LOCK_MS, OWNER, VAULT_KEY } from "./config.js";
import { api } from "./github.js";
import { toast } from "./lib/dom.js";
import { fromBase64, toBase64, utf8 } from "./lib/format.js";
import { state } from "./state.js";
import { ui } from "./ui/hooks.js";

async function deriveKey(passphrase, salt) {
  const base = await crypto.subtle.importKey("raw", utf8(passphrase), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations: 310_000, hash: "SHA-256" }, base,
    { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

export const hasSavedToken = () => Boolean(localStorage.getItem(VAULT_KEY));
export const forgetSavedToken = () => localStorage.removeItem(VAULT_KEY);

export async function rememberToken(token, passphrase) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await deriveKey(passphrase, salt), utf8(token)));
  localStorage.setItem(VAULT_KEY, JSON.stringify({ salt: toBase64(salt), iv: toBase64(iv), data: toBase64(data) }));
}

export async function unlockToken(passphrase) {
  const vault = JSON.parse(localStorage.getItem(VAULT_KEY));
  const key = await deriveKey(passphrase, fromBase64(vault.salt));
  try {
    return new TextDecoder().decode(await crypto.subtle.decrypt({ name: "AES-GCM", iv: fromBase64(vault.iv) }, key, fromBase64(vault.data)));
  } catch {
    throw new Error("That passphrase doesn't unlock the saved token.");
  }
}

/** Accepts only a fine-grained token that belongs to the owner. */
export async function connect(token) {
  token = token.trim();
  if (!token.startsWith("github_pat_")) {
    throw new Error("Use a fine-grained token (it starts with github_pat_). Classic tokens can reach all your repositories.");
  }
  state.token = token;
  try {
    const user = await api("/user");
    if (user.login.toLowerCase() !== OWNER.toLowerCase()) throw new Error(`This token belongs to ${user.login}; only ${OWNER} can save.`);
    state.user = user.login;
  } catch (error) {
    state.token = "";
    state.user = "";
    throw error.status === 401 ? new Error("GitHub rejected that token. It may have expired or been revoked.") : error;
  }
  armIdleLock();
}

export function lock(message = "Locked. The token is no longer in memory.") {
  state.token = "";
  state.user = "";
  clearTimeout(state.idleTimer);
  ui.all();
  toast(message);
}

export function armIdleLock() {
  clearTimeout(state.idleTimer);
  if (state.token) state.idleTimer = setTimeout(() => lock("Locked after 30 minutes without activity."), IDLE_LOCK_MS);
}
