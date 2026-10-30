// Logo previews, uploads (resized PNGs or script-free SVGs) and the logo dropdowns.

import { BRANCH, RAW } from "../config.js";
import { h, toast } from "../lib/dom.js";
import { toBase64, utf8 } from "../lib/format.js";
import { state } from "../state.js";
import { redraw } from "./hooks.js";

const logoUrl = (file) => state.uploads[file]?.preview || `${RAW}/${BRANCH}/assets/logos/${encodeURIComponent(file)}`;

export function disc(file, kind = "") {
  return h("span", { class: `disc ${kind}${file ? "" : " empty"}`, "aria-hidden": "true" },
    file ? h("img", { src: logoUrl(file), alt: "", referrerpolicy: "no-referrer" }) : null);
}

function uniqueName(base, ext) {
  const slug = (base.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "logo").slice(0, 40);
  let name = `${slug}.${ext}`;
  for (let n = 2; state.logos.includes(name) || state.uploads[name]; n++) name = `${slug}-${n}.${ext}`;
  return name;
}

async function prepareLogo(file, base) {
  if (file.size > 2_000_000) throw new Error("Pick an image under 2 MB.");
  if (/\.svg$/i.test(file.name) || file.type === "image/svg+xml") {
    const text = await file.text();
    if (!/<svg[\s>]/i.test(text) || /<script|<foreignObject|\son[a-z]+\s*=|javascript:|<!ENTITY/i.test(text)) {
      throw new Error("That SVG contains scripts or isn't a plain SVG. Use another file or a PNG.");
    }
    if (text.length > 100_000) throw new Error("Keep SVG logos under 100 KB.");
    const base64 = toBase64(utf8(text));
    return { name: uniqueName(base, "svg"), base64, preview: `data:image/svg+xml;base64,${base64}` };
  }
  if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) throw new Error("Use a PNG, JPEG, WebP or SVG file.");
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 192 / Math.max(bitmap.width, bitmap.height));   // small: logos are embedded in every widget
  const canvas = h("canvas", { width: Math.max(1, Math.round(bitmap.width * scale)), height: Math.max(1, Math.round(bitmap.height * scale)) });
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const preview = canvas.toDataURL("image/png");
  return { name: uniqueName(base, "png"), base64: preview.split(",")[1], preview };
}

function pickFile() {
  return new Promise((resolve) => {
    const input = h("input", { type: "file", accept: ".png,.jpg,.jpeg,.webp,.svg,image/png,image/jpeg,image/webp,image/svg+xml" });
    input.addEventListener("change", () => resolve(input.files[0] || null));
    input.addEventListener("cancel", () => resolve(null));
    input.click();
  });
}

/** Every logo that will exist after saving: the library plus uploads, minus deletions. */
export const libraryFiles = ({ includeDeleted = false } = {}) => [...new Set([...state.logos, ...Object.keys(state.uploads)])]
  .filter((file) => includeDeleted || !state.deletions.has(file)).sort();

export function logoSelect(value, base, onPick, label = "Logo") {
  return h("label", {}, label,
    h("select", {
      onchange: async (event) => {
        const choice = event.target.value;
        if (choice !== "__upload__") { onPick(choice); redraw(); return; }
        try {
          const file = await pickFile();
          if (file) {
            const logo = await prepareLogo(file, base);
            state.uploads[logo.name] = logo;
            onPick(logo.name);
            toast(`${logo.name} will be uploaded when you save.`);
          }
        } catch (error) {
          toast(error.message);
        }
        redraw();
      },
    },
    h("option", { value: "", selected: !value }, "Choose a logo…"),
    libraryFiles().map((file) => h("option", { value: file, selected: file === value }, state.uploads[file] ? `${file} (new)` : file)),
    h("option", { value: "__upload__" }, "Upload a new logo…")));
}

/** Light- and dark-theme wordmark dropdowns for an entry shown as a wordmark. */
export function wordmarkSelects(entry, base) {
  return [logoSelect(entry.wordmark.light, `${base}-light`, (f) => { entry.wordmark.light = f; }, "Wordmark (light theme)"),
    logoSelect(entry.wordmark.dark, `${base}-dark`, (f) => { entry.wordmark.dark = f; }, "Wordmark (dark theme)")];
}

/** The preview for an entry: its light wordmark, or its logo. */
export const entryDisc = (entry, logoKind) => (entry.wordmark ? disc(entry.wordmark.light, "wordmark") : disc(entry.logo, logoKind));
