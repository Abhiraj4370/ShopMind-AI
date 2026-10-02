# ShopMind AI v9 — Intelligence + Commerce Upgrade

This release builds on v8 and adds the full next-stage product intelligence layer.

## Added

1. Live region + pincode-ready location context
2. Instant-delivery source separation
3. Price history storage
4. Deterministic price signal (`good_time_to_buy`, `above_recent_average`, etc.)
5. Transparent ShopMind score
6. Review/rating intelligence (aggregate signal, never fabricated quotes)
7. Server-side smart filters
8. Conversational shopping clarification endpoint
9. Wishlist persistence
10. Price-drop alert persistence + background checker when Tavily is configured
11. Multi-item shopping remains supported by the existing planner/optimizer
12. Best Overall / Top Rated / Cheapest / Fastest signals
13. Source verification metadata
14. Price confidence metadata
15. Product/search caching with TTL
16. Guest profile IDs stored locally in the browser
17. Optional account register/login with salted scrypt password hashing
18. Admin statistics endpoint protected by `ADMIN_API_KEY`
19. Persistent SQLite storage with a migration-friendly schema
20. Expanded regional retailer registry

## Storage

SQLite is the default local storage so the project runs without requiring a database server. Set `SHOPMIND_DB_PATH` to move the file. The schema separates searches, products, price history, wishlist, alerts, users and events.

## Security notes

- API keys stay server-side.
- Shopping sessions require capability tokens.
- Admin stats require a separate admin key.
- Passwords use salted `scrypt` hashes.
- External merchant discovery remains disabled by default.
- External product prices are never fabricated when a source does not expose a price.
- Instant-delivery windows are not treated as live ETAs unless source data provides them.

## Local run

```powershell
cd D:\ShopMind-AI
.\.venv\Scripts\Activate.ps1
python -m pytest -q
python -m uvicorn shopmind_ai.main:app --host 127.0.0.1 --port 8020 --reload
```

Frontend:

```powershell
cd frontend
npm install
npm run build
npm run dev
```

Optional `.env` values:

```env
SHOPMIND_DB_PATH=data/shopmind.db
ADMIN_API_KEY=change-this-in-production
```
