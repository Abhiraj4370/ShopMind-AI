# ShopMind AI v6 — Instant Delivery Home Section

Added an India-only Instant Delivery section on the home page.

Quick-commerce sources are explicitly separated from standard e-commerce sources:
- Blinkit
- Zepto
- Swiggy Instamart
- bbnow
- Flipkart Minutes

The backend marks these sources as `instant_delivery=True` and supports an `instant_only` regional search mode when an India query explicitly asks for instant/quick delivery or a 10–30 minute window.

Important: the displayed time is an indicative service window, not a guaranteed ETA. Actual availability depends on pincode, inventory, traffic, operating hours and the retailer's live checkout ETA.
