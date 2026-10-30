// Tab id → panel module. Each module exports panel(), and choices() when it has a filterable list.

import * as banner from "./banner.js";
import * as collaborations from "./collaborations.js";
import * as coverage from "./coverage.js";
import * as logoLibrary from "./logo-library.js";
import * as trackRecord from "./track-record.js";
import * as watchlist from "./watchlist.js";

export const PANELS = { watchlist, collabs: collaborations, coverage, record: trackRecord, banner, logos: logoLibrary };
