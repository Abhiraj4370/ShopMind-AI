# ShopMind v17 — Reliability & UX Fixes

## Fixed
- Search suggestion buttons now preserve their intended mode (AI Shop / Compare / Instant) and pass a valid pincode to instant searches.
- Product and comparison score rendering now accepts both normalized `0–1` and percentage `0–100` score payloads.
- Instant-only results now enforce the advertised `≤30 min` ETA when a numeric ETA is available.
- Added a proper empty-results state instead of leaving a blank results page.
- Added a safe missing-product state for the details page.
- Guest ID generation now uses `globalThis.crypto` safely.
- Health checks have a bounded 5-second timeout.
- Session polling now tolerates up to three transient fetch failures before failing the search.
- Manual pincode search validates the 6-digit requirement before submitting.
- Added keyboard focus states, mobile overflow handling, text clamping and card robustness for long product names/features.

## Notes
The project intentionally does not claim live retailer inventory, coupons or guaranteed ETAs without a real retailer/affiliate API. Those values remain source-dependent.
