// Banner: the photo at the top of the profile. Pick an earlier one or upload a new one.

import { BRANCH, RAW } from "../../config.js";
import { h, toast } from "../../lib/dom.js";
import { toBase64 } from "../../lib/format.js";
import { state } from "../../state.js";
import { textField } from "../controls.js";
import { redraw } from "../hooks.js";

const MAX_WIDTH = 2400;
const MIN_WIDTH = 1200;
const SIZE_HINT = "Recommended 2400 × 800 px (3:1); at least 1200 × 400 px. PNG, JPEG or WebP.";
const ratioNote = (w, h) => (Math.abs(w / h - 3) > 0.35 ? ` It is ${(w / h).toFixed(2)}:1, so it will look ${w / h > 3 ? "flatter" : "taller"} than 3:1.` : "");
const bannerUrl = (file) => state.bannerUploads[file]?.preview || `${RAW}/${BRANCH}/assets/banners/${encodeURIComponent(file)}`;

function uniqueName(base, ext) {
  const slug = (base.toLowerCase().replace(/\.[a-z0-9]+$/, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "banner").slice(0, 40);
  let name = `${slug}.${ext}`;
  for (let n = 2; state.banners.includes(name) || state.bannerUploads[name]; n++) name = `${slug}-${n}.${ext}`;
  return name;
}

/** Small PNGs are kept as they are; anything else is scaled to at most 2400px wide and saved as JPEG. */
async function prepareBanner(file) {
  if (!/^image\/(png|jpeg|webp)$/.test(file.type)) throw new Error("Use a PNG, JPEG or WebP photo.");
  if (file.size > 15_000_000) throw new Error("Pick a photo under 15 MB.");
  const bitmap = await createImageBitmap(file);
  if (bitmap.width < MIN_WIDTH) {
    throw new Error(`That photo is ${bitmap.width} × ${bitmap.height} px; a banner needs to be at least ${MIN_WIDTH} px wide.`);
  }
  if (file.type === "image/png" && file.size < 3_000_000 && bitmap.width <= MAX_WIDTH) {
    const base64 = toBase64(new Uint8Array(await file.arrayBuffer()));
    return { name: uniqueName(file.name, "png"), base64, preview: `data:image/png;base64,${base64}` };
  }
  const scale = Math.min(1, MAX_WIDTH / bitmap.width);
  const canvas = h("canvas", { width: Math.round(bitmap.width * scale), height: Math.round(bitmap.height * scale) });
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const preview = canvas.toDataURL("image/jpeg", 0.9);
  return { name: uniqueName(file.name, "jpg"), base64: preview.split(",")[1], preview };
}

function upload() {
  const input = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp" });
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    try {
      const banner = await prepareBanner(file);
      state.bannerUploads[banner.name] = banner;
      state.config.banner = { ...(state.config.banner || {}), file: banner.name };
      const size = await createImageBitmap(file);
      toast(`${banner.name} will be uploaded when you save.${ratioNote(size.width, size.height)}`);
    } catch (error) {
      toast(error.message);
    }
    redraw();
  });
  input.click();
}

/** The preview, with the photo's real size underneath once it has loaded. */
function previewWithSize(file) {
  const size = h("p", { class: "hint banner-size" }, "Measuring…");
  const img = h("img", { class: "banner-preview", src: bannerUrl(file), alt: "", referrerpolicy: "no-referrer" });
  img.addEventListener("load", () => {
    const { naturalWidth: w, naturalHeight: tall } = img;
    size.textContent = `This photo: ${w} × ${tall} px.${w < MIN_WIDTH ? ` Below the ${MIN_WIDTH} px minimum.` : ""}${ratioNote(w, tall)}`;
    size.classList.toggle("error", w < MIN_WIDTH);
  });
  return [img, size];
}

export function panel() {
  const banner = state.config.banner ||= { file: "", alt: "" };
  const files = [...new Set([...state.banners, ...Object.keys(state.bannerUploads)])].sort();
  return [
    h("div", { class: "panel-head" }, h("h2", {}, "Banner"),
      h("p", {}, "The photo at the top of your profile, shown as it is, without a link."),
      h("p", { class: "size-hint" }, SIZE_HINT)),
    ...(banner.file ? previewWithSize(banner.file) : [h("p", { class: "empty-state" }, "No banner chosen.")]),
    h("div", { class: "fields banner-fields" },
      h("label", {}, "Photo", h("select", { onchange: (event) => { banner.file = event.target.value; redraw(); } },
        files.map((file) => h("option", { value: file, selected: file === banner.file }, state.bannerUploads[file] ? `${file} (new)` : file)))),
      textField("Description for screen readers", banner.alt, (v) => { banner.alt = v; }, { maxlength: 160, class: "span-2" })),
    h("div", { class: "toolbar" }, h("button", { class: "btn", type: "button", onclick: upload }, "Upload a new photo")),
  ];
}
