// The sign-in card: token or passphrase entry, or the signed-in status with Sign out and Forget.
// Nothing else on the page is shown until a valid token is connected.

import { $, h, toast } from "../lib/dom.js";
import { connect, forgetSavedToken, hasSavedToken, rememberToken, signOut, unlockToken } from "../session.js";
import { state } from "../state.js";

const guide = () => h("details", {}, h("summary", {}, "How to create the token"),
  h("ol", {},
    h("li", {}, "GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token."),
    h("li", {}, "Resource owner: Haoming9527. Expiration: 90 days or less."),
    h("li", {}, "Repository access: Only select repositories → Haoming9527/Haoming9527."),
    h("li", {}, "Permissions → Repository → Contents: Read and write. Nothing else."),
    h("li", {}, "Generate, copy it, and paste it here. GitHub shows it only once.")));

const status = (on, text) => h("span", { class: "status" }, h("span", { class: on ? "dot on" : "dot" }), text);

function signedIn() {
  return [h("div", { class: "row" }, status(true, `Signed in as ${state.user}`),
    h("button", { class: "btn small", type: "button", onclick: () => signOut() }, "Sign out"),
    h("button", { class: "btn small danger", type: "button", onclick: () => { forgetSavedToken(); signOut("Signed out and forgot the token on this device."); } },
      "Forget token"))];
}

function passphraseForm(onSignedIn, fail, message) {
  const pass = h("input", { type: "password", placeholder: "Passphrase", autocomplete: "current-password", "aria-label": "Passphrase" });
  const unlock = async () => {
    try { await connect(await unlockToken(pass.value)); await onSignedIn(); toast("Signed in."); }
    catch (error) { fail(error); }
  };
  pass.addEventListener("keydown", (e) => { if (e.key === "Enter") unlock(); });
  return [h("div", { class: "row" }, status(false, "Enter your passphrase to sign in."),
    pass, h("button", { class: "btn primary", type: "button", onclick: unlock }, "Sign in"),
    h("button", { class: "btn small danger", type: "button", onclick: () => { forgetSavedToken(); renderSignIn(onSignedIn); } }, "Forget saved token")),
  message];
}

function tokenForm(onSignedIn, fail, message) {
  const token = h("input", { type: "password", placeholder: "github_pat_…", autocomplete: "off", spellcheck: "false", "aria-label": "Fine-grained token" });
  const remember = h("input", { type: "checkbox", id: "remember" });
  const pass = h("input", { type: "password", placeholder: "Passphrase to protect it (8+ characters)", autocomplete: "new-password",
    "aria-label": "Passphrase", hidden: true });
  remember.addEventListener("change", () => { pass.hidden = !remember.checked; });
  const go = async () => {
    try {
      if (remember.checked && pass.value.length < 8) throw new Error("Choose a passphrase of at least 8 characters to remember the token.");
      await connect(token.value);
      if (remember.checked) await rememberToken(state.token, pass.value);
      await onSignedIn();
      toast(remember.checked ? "Signed in. The token is saved, encrypted with your passphrase." : "Signed in for this visit.");
    } catch (error) { fail(error); }
  };
  token.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  return [h("div", { class: "row" }, status(false, "Sign in with your access token to manage the board."),
    token, h("button", { class: "btn primary", type: "button", onclick: go }, "Sign in")),
  h("div", { class: "row" }, h("label", { class: "hint" }, remember, " Remember on this device, protected by a passphrase"), pass),
  message, guide()];
}

/** Draws the card. onSignedIn runs after a token is accepted. */
export function renderSignIn(onSignedIn) {
  const message = h("p", { class: "hint error", role: "alert" });
  const fail = (error) => { message.textContent = error.message; };
  const content = state.user ? signedIn()
    : hasSavedToken() ? passphraseForm(onSignedIn, fail, message)
    : tokenForm(onSignedIn, fail, message);
  $("#token").replaceChildren(...content);
}
