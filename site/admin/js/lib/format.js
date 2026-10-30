// Pure helpers: byte encoding, profile.json formatting and display text. No DOM, no network.

export const utf8 = (text) => new TextEncoder().encode(text);
export const toBase64 = (bytes) => { let s = ""; for (const b of bytes) s += String.fromCharCode(b); return btoa(s); };
export const fromBase64 = (text) => Uint8Array.from(atob(text.replace(/\s/g, "")), (c) => c.charCodeAt(0));
export const clone = (value) => JSON.parse(JSON.stringify(value));

const compact = (v) => Array.isArray(v) ? `[${v.map(compact).join(", ")}]`
  : v && typeof v === "object" ? `{${Object.entries(v).map(([k, x]) => `${JSON.stringify(k)}: ${compact(x)}`).join(", ")}}`
  : JSON.stringify(v);

/** profile.json in its existing style: one line per list item. */
export function formatConfig(config) {
  const keys = Object.keys(config);
  const lines = keys.map((key, i) => {
    const value = config[key];
    const tail = i < keys.length - 1 ? "," : "";
    if (Array.isArray(value) && value.length) {
      const items = value.map((item, j) => `    ${compact(item)}${j < value.length - 1 ? "," : ""}`);
      return `  ${JSON.stringify(key)}: [\n${items.join("\n")}\n  ]${tail}`;
    }
    return `  ${JSON.stringify(key)}: ${compact(value)}${tail}`;
  });
  return `{\n${lines.join("\n")}\n}\n`;
}

export const prettyName = (repo) => repo.split("/").pop().replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim();

export function suggestTicker(name) {
  const words = name.split(/[-_\s.]+/).filter(Boolean);
  const value = words.length > 1 ? words.map((w) => w[0]).join("") : name.replace(/[^A-Za-z0-9]/g, "").slice(0, 4);
  return value.toUpperCase().slice(0, 5);
}

export function since(iso) {
  const days = Math.floor((Date.now() - Date.parse(iso)) / 86_400_000);
  return days < 1 ? "today" : days < 30 ? `${days}d ago` : days < 365 ? `${Math.floor(days / 30)}mo ago` : `${Math.floor(days / 365)}y ago`;
}
