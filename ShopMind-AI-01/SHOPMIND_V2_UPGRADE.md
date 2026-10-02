# ShopMind AI v2 upgrade notes

This version keeps the existing UCP/session/graph architecture and improves it in place.

## Automatic AI provider routing

The frontend no longer asks the user to choose an AI provider.

The backend automatically tries providers in:

```text
Gemini → Groq → Mistral → OpenRouter → keyword fallback
```

A provider is skipped when its key is missing, and a failed provider does not stop the
shopping workflow.

Optional variables:

```env
MISTRAL_API_KEY=
OPENROUTER_API_KEY=
MISTRAL_MODEL=mistral-large-latest
OPENROUTER_MODEL=openrouter/free
AI_PROVIDER_ORDER=gemini,groq,mistral,openrouter
TAVILY_API_KEY=
```

## Regional shopping

With `TAVILY_API_KEY` configured, ShopMind adds region-aware web search on top of UCP
merchants. The source registry includes curated regional domains such as Amazon India,
Flipkart, Myntra, Croma, Reliance Digital, Amazon regional sites, Walmart, Best Buy,
Currys and noon.

The regional adapter does not invent missing price/rating data. Unknown prices are never
treated as free products.

## Budget and currency

- Region is resolved from explicit API data, browser locale, then best-effort IP lookup.
- Explicit currency markers in the query are preserved.
- Budgets expressed in a currency different from the display currency are converted
  before local budget filtering.
- If no exact product fits the budget, closest real products may be shown without
  changing their price.

## Security hardening

- Restricted CORS instead of `*`.
- External UCP discovery disabled by default.
- Outbound UCP URLs validated to reduce SSRF risk.
- Redirects disabled for merchant HTTP requests.
- Query length and session creation rate limits.
- Production API docs disabled.
- Frontend product links restricted to HTTP/HTTPS.
- `.env.example` contains placeholders rather than API-key values.

This is hardened for a demo/local deployment, not literally "hacker proof". Production
needs authentication, TLS, a persistent rate limiter, secrets management, network
egress controls, monitoring and a reverse proxy/WAF.

## Validation

```powershell
python -m py_compile .\src\shopmind_ai\api.py
python -m py_compile .\src\shopmind_ai\models.py
python -m py_compile .\src\shopmind_ai\orchestrator\planner.py
python -m py_compile .\src\shopmind_ai\orchestrator\graph.py
python -m py_compile .\src\shopmind_ai\agents\search_agent.py
python -m py_compile .\src\shopmind_ai\services
egional_search.py
python -m py_compile .\src\shopmind_ai\services
egional_sources.py
python -m pytest -q

cd frontend
npm install
npm run build
```
