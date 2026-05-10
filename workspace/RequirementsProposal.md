# URL Shortener Service

Build a URL shortener REST API that allows anonymous users to create, access, and view statistics for shortened URLs.

## Scope
Single-session MVP implementation by one development team. Excludes: user accounts, authentication, custom short codes, URL expiration, bulk operations.

## Technology Stack
- Python 3.10+
- FastAPI web framework
- PostgreSQL 14+ database
- Docker containerization
- Redis for rate limiting (implicit dependency added)

## Actors
- **Anonymous User**: Any client making HTTP requests to the service
- **System**: The FastAPI application and its background processes
- **Database**: PostgreSQL instance storing URL mappings and metadata

---

## Functional Requirements

### FR-1: URL Shortening
**Description**: Anonymous users can submit a long URL and receive a unique short code.

**Acceptance Criteria**:

1. **Given** an anonymous user has a valid HTTP/HTTPS URL (max 2048 characters)
   **When** they POST to `/shorten` with JSON body `{"url": "<long_url>"}`
   **Then** the system returns HTTP 201 with JSON `{"short_code": "<code>", "short_url": "https://domain/{code}"}`
   **And** the short code is 6-8 alphanumeric characters
   **And** the mapping is persisted in PostgreSQL within 200ms (p95)

2. **Given** an anonymous user submits an invalid URL (missing protocol, malformed, non-HTTP(S))
   **When** they POST to `/shorten`
   **Then** the system returns HTTP 400 with JSON `{"error": "Invalid URL format"}`
   **And** no database write occurs

3. **Given** an anonymous user submits the same long URL twice
   **When** they POST to `/shorten` with an already-shortened URL
   **Then** the system returns HTTP 200 with the existing short code
   **And** no duplicate entry is created

4. **Given** the database connection is unavailable
   **When** an anonymous user POSTs to `/shorten`
   **Then** the system returns HTTP 503 with JSON `{"error": "Service temporarily unavailable"}`

---

### FR-2: URL Redirection
**Description**: Anonymous users can access the original URL by visiting the short code endpoint.

**Acceptance Criteria**:

1. **Given** a short code exists in the database
   **When** an anonymous user sends GET `/{code}`
   **Then** the system returns HTTP 301 redirect to the original URL
   **And** increments the click count for that code
   **And** response time is < 100ms (p95)

2. **Given** a short code does NOT exist in the database
   **When** an anonymous user sends GET `/{code}`
   **Then** the system returns HTTP 404 with JSON `{"error": "Short code not found"}`

3. **Given** the database connection is unavailable
   **When** an anonymous user sends GET `/{code}`
   **Then** the system returns HTTP 503 with JSON `{"error": "Service temporarily unavailable"}`

---

### FR-3: URL Statistics
**Description**: Anonymous users can retrieve usage statistics for a short code.

**Acceptance Criteria**:

1. **Given** a short code exists in the database
   **When** an anonymous user sends GET `/stats/{code}`
   **Then** the system returns HTTP 200 with JSON:
   ```json
   {
     "short_code": "<code>",
     "original_url": "<url>",
     "click_count": <integer>,
     "created_at": "<ISO 8601 timestamp>"
   }
   ```

2. **Given** a short code does NOT exist
   **When** an anonymous user sends GET `/stats/{code}`
   **Then** the system returns HTTP 404 with JSON `{"error": "Short code not found"}`

3. **Given** the database connection is unavailable
   **When** an anonymous user sends GET `/stats/{code}`
   **Then** the system returns HTTP 503 with JSON `{"error": "Service temporarily unavailable"}`

---

## Non-Functional Requirements

### NFR-1: Rate Limiting
**Description**: Prevent abuse by limiting requests per IP address.

**Acceptance Criteria**:

1. **Given** an anonymous user's IP address has made fewer than 100 requests in the current 60-second window
   **When** they make any API request (POST /shorten, GET /{code}, GET /stats/{code})
   **Then** the request is processed normally

2. **Given** an anonymous user's IP address has made 100 or more requests in the current 60-second window
   **When** they make any additional API request
   **Then** the system returns HTTP 429 with JSON `{"error": "Rate limit exceeded. Try again in <seconds> seconds"}`
   **And** the `Retry-After` header indicates seconds until reset

3. **Given** the rate limiting service (Redis) is unavailable
   **When** any request is made
   **Then** the system ALLOWS the request (fail-open behavior)
   **And** logs a warning about rate limiter failure

---

### NFR-2: Data Persistence
**Description**: All URL mappings and statistics must survive service restarts.

**Acceptance Criteria**:

1. **Given** a short code was created before a service restart
   **When** the service restarts and an anonymous user accesses GET `/{code}`
   **Then** the redirect works and click count increments correctly

2. **Given** the PostgreSQL schema includes tables: `urls` (id, short_code, original_url, created_at) and `clicks` (id, short_code, clicked_at)
   **When** the service starts
   **Then** database migrations apply automatically via Alembic or equivalent

---

### NFR-3: Deployment
**Description**: Service must run in a Docker container for consistent deployment.

**Acceptance Criteria**:

1. **Given** a `Dockerfile` and `docker-compose.yml` exist in the repository
   **When** an operator runs `docker-compose up`
   **Then** the FastAPI service, PostgreSQL, and Redis start successfully
   **And** the API is accessible on `http://localhost:8000`

2. **Given** environment variables for database connection (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)
   **When** the container starts
   **Then** the service connects to PostgreSQL using those credentials
   **Or** fails fast with a clear error message if connection fails

---

## Out of Scope (Explicitly Excluded from MVP)

- User authentication or account management
- Custom short codes (user-specified aliases)
- URL expiration or TTL
- Bulk shortening operations
- Analytics dashboard or UI
- HTTPS enforcement (assumes reverse proxy handles TLS)
- Geographic click tracking
- QR code generation

---

## Summary of Changes from Original

1. **Added structured acceptance criteria**: Every requirement now has Given/When/Then criteria (15 total across the document)
2. **Defined all actors**: Anonymous User, System, Database explicitly named
3. **Added error paths**: Database unavailability, rate limit exceeded, invalid inputs all covered
4. **Quantified all metrics**: Response times (200ms, 100ms p95), rate limits (100 req/min), URL length (2048 chars)
5. **Named external dependencies**: Redis for rate limiting, Alembic for migrations
6. **Defined scope boundaries**: Explicit "Out of Scope" section clarifies single-session deliverable
7. **Added fail-safe behavior**: Rate limiter fails open, database failures return 503
8. **Specified data schema**: Tables and columns for persistence requirements
