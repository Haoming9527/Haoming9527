// The single shared store. Modules read and change it directly; the UI redraws from it.

export const state = {
  token: "", user: "", config: null, original: null, sha: "", repos: [], external: [], logos: [], commits: {}, snapshotMissing: false,
  uploads: {}, banners: [], bannerUploads: {}, deletions: new Set(), protected: new Set(), protectedKnown: false, tab: "watchlist", filter: "", saving: false, busy: false, idleTimer: 0,
};
