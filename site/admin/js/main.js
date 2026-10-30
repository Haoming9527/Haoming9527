// Board manager: edits profile.json for the Haoming9527 profile board.
//
// Security model
// - GitHub decides who can write: saving needs a fine-grained token with write access to this
//   one repository, which only its owner can create. The checks below are defence in depth.
// - The token lives in memory. "Remember" stores it only encrypted with a passphrase
//   (PBKDF2 + AES-GCM), because every Pages site on haoming9527.github.io shares this origin.
// - It is sent only to api.github.com, never rendered, and forgotten after 30 idle minutes.
// - The page writes nothing but profile.json and files in assets/logos, and deletes only
//   logos that nothing on the board uses.
//
// Layout
// - config.js, state.js: the repository it edits and the shared store.
// - github.js, session.js, board.js: the API client, the token, and the profile.json model
//   (load, validate, commit). None of these touch the DOM.
// - ui/: the sign-in card, shared controls, the logo picker, and one module per tab in ui/panels/.

import { isDirty } from "./board.js";
import { armIdleLock } from "./session.js";
import { startUi } from "./ui/render.js";

if (window.top !== window.self) {
  document.documentElement.textContent = "";
  throw new Error("The board manager refuses to run inside a frame.");
}

["pointerdown", "keydown"].forEach((type) => window.addEventListener(type, armIdleLock, { passive: true }));
window.addEventListener("beforeunload", (event) => { if (isDirty()) event.preventDefault(); });

startUi();
