# ── Stage 1: base OS + system deps ────────────────────────────────────────────
FROM python:3.10-slim AS base

# System packages (mirrors system-deps.txt)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-venv \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Stage 2: Python deps ───────────────────────────────────────────────────────
FROM base AS deps

# Install Python dependencies (mirrors requirements.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 3: application ───────────────────────────────────────────────────────
FROM deps AS app

COPY . .

# Persist company state and projects outside the container
VOLUME ["/app/company", "/app/projects"]

# Required at runtime — pass with: docker run -e ANTHROPIC_API_KEY=sk-ant-...
ENV ANTHROPIC_API_KEY=""
ENV AICOMPANY_MODEL="claude-sonnet-4-6"

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
