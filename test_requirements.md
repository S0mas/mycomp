# URL Shortener Service

Build a URL shortener REST API with the following features:

- POST /shorten — accepts a long URL, returns a short code
- GET /{code} — redirects to the original URL
- GET /stats/{code} — returns click count and creation date
- Store URLs in PostgreSQL
- Use FastAPI framework
- Include rate limiting (100 requests/minute per IP)
- Add input validation (reject invalid URLs)
- Return proper HTTP status codes (201, 301, 404, 429)

## Constraints
- Python 3.10+
- Docker deployment
- No authentication required for MVP
