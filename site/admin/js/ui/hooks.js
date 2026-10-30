// Redraw hooks. ui/render.js fills these in at start-up, so panels and the session can ask for a
// redraw without importing the renderer (which imports them).

export const ui = {
  all() {},
  panel() {},
  edited() {},
  picker() { return null; },
};

/** After an edit that changes what the panel shows: redraw it, the tape and the save bar. */
export const redraw = () => { ui.panel(); ui.edited(); };
