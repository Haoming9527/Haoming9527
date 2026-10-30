// The one repository the board manager edits, and the rules for what it may write there.

export const OWNER = "Haoming9527";
export const REPO = "Haoming9527";
export const BRANCH = "main";
export const API = "https://api.github.com";
export const RAW = `https://raw.githubusercontent.com/${OWNER}/${REPO}`;
export const VAULT_KEY = "board-manager.vault.v1";
export const IDLE_LOCK_MS = 30 * 60 * 1000;
export const LOGO_FILE = /^[A-Za-z0-9][A-Za-z0-9._-]*\.(svg|png|jpe?g)$/i;
export const WRITABLE = [/^profile\.json$/, /^assets\/logos\/[a-z0-9][a-z0-9-]*\.(png|svg)$/];
export const DELETABLE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
export const TABS = [["watchlist", "Watchlist"], ["collabs", "Collaborations"], ["coverage", "Chart coverage"], ["record", "Track record"], ["logos", "Logos"]];
export const SECTIONS = { watchlist: "projects", collabs: "collaborations", coverage: "activity_repositories", record: "achievements", logos: null };
