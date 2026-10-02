# ShopMind AI Security Notes

ShopMind AI is designed with defense-in-depth, not a claim of being "hacker proof".

## Enabled safeguards

- API keys stay server-side in `.env`.
- CORS is restricted to configured frontend origins.
- Shopping query length and rate limits are enforced.
- Production API docs can be disabled through `ENVIRONMENT`.
- Security response headers include CSP, frame protection, MIME sniffing protection and referrer policy.
- External UCP discovery is disabled by default.
- UCP outbound requests reject private/link-local/reserved IP literals and require HTTPS for non-local hosts.
- HTTP redirects are disabled for UCP requests to reduce SSRF/redirect abuse.
- Regional search uses an allowlisted source registry rather than arbitrary retailer URLs.
- External product links are validated on the frontend before opening.
- Product prices are never fabricated as zero when a source does not expose a price.
- Unexpected server errors return generic details instead of stack/error text.

## Production recommendations

1. Use HTTPS behind a reverse proxy.
2. Set a strict `ALLOWED_ORIGINS` value.
3. Rotate API keys if they were ever exposed.
4. Use Redis/database-backed sessions instead of the in-memory session manager.
5. Put authentication and authorization in front of checkout/order endpoints.
6. Add an external WAF/rate limiter for public deployments.
7. Use official retailer/affiliate APIs where available instead of scraping.
