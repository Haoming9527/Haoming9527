// DOM helpers. Elements are always built with createElement and text nodes, never innerHTML.

export const $ = (selector) => document.querySelector(selector);

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "value") el.value = value;
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));   // never innerHTML
  }
  return el;
}

export function toast(message, link) {
  const box = $("#toast");
  box.replaceChildren(message, link ? h("span", {}, " ", h("a", { href: link.href, rel: "noopener" }, link.label)) : "");
  box.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => box.classList.remove("show"), 6000);
}
