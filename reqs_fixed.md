# Task Manager API

## Overview
Build a RESTful API for managing personal tasks, deployed as a Docker container.

## Features
1. **User registration & login** — email/password, JWT tokens, refresh flow
2. **CRUD tasks** — each task has: title (str, required), description (text, optional),
   status (enum: todo/in_progress/done), due_date (datetime, optional), priority (1-5)
3. **List tasks** — paginated, filterable by status and priority, sortable by due_date
4. **Assign labels** — many-to-many relationship, CRUD on labels

## Technical Constraints
- Python 3.11+, FastAPI, SQLAlchemy 2.0, PostgreSQL 15
- Alembic for migrations
- pytest with >80% coverage
- OpenAPI docs auto-generated

## Acceptance Criteria
- All endpoints return proper HTTP status codes (201 for create, 404 for not found, etc.)
- Auth endpoints rate-limited to 5 req/min
- Response time < 200ms for list endpoints (100 items)
- Passwords hashed with bcrypt, never stored in plain text
