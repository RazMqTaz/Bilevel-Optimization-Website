# Docker Architecture

This document describes how the SACE framework application is containerized, how the services interact, and the design decisions behind the current Docker setup.

## Overview

The application is composed of four services, orchestrated with Docker Compose:

| Service | Role | Port |
|---|---|---|
| **api** | FastAPI backend — handles job submissions, config validation, and status polling | 8000 |
| **worker** | Celery worker — picks up optimization jobs from the queue and runs the SACE framework | — |
| **redis** | Message broker and result backend for Celery | 6379 |
| **frontend** | Streamlit dashboard — user-facing interface for submitting and monitoring jobs | 8501 |

SQLite is used as the lightweight persistence layer. The database file lives on a mounted Docker volume so data survives container restarts.

## Architecture Diagram

```
┌────────────────────────────────────────────────────────┐
│                     Docker Host                        │
│                                                        │
│  ┌──────────┐    HTTP     ┌──────────┐                 │
│  │ frontend │ ──────────> │   api    │                 │
│  │ Streamlit│  (polling)  │ FastAPI  │                 │
│  │  :8501   │             │  :8000   │                 │
│  └──────────┘             └────┬─────┘                 │
│                                │                       │
│                         enqueue task                   │
│                                │                       │
│                           ┌────▼─────┐                 │
│                           │  redis   │                 │
│                           │  :6379   │                 │
│                           └────┬─────┘                 │
│                                │                       │
│                          pick up task                  │
│                                │                       │
│                           ┌────▼─────┐                 │
│                           │  worker  │                 │
│                           │  Celery  │                 │
│                           └──────────┘                 │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Volumes: ./data (SQLite DB), ./results (output) │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

## Request Flow

1. The user interacts with the **Streamlit frontend**, which collects optimization parameters and builds a JSON configuration.
2. The frontend sends the config to the **FastAPI backend** via an HTTP POST request.
3. The API validates the config using a strict Pydantic-based validator (`config_validator.py`), rejects anything malformed (HTTP 422), and persists the sanitized config to SQLite.
4. The API dispatches the job to **Redis** via a Celery task call.
5. The **Celery worker** picks up the task, performs a defense-in-depth re-validation of the config, then invokes the SACE optimization framework.
6. The frontend polls the API at ~2-second intervals for job status and results. (WebSocket streaming was evaluated but dropped due to asyncio compatibility issues with Streamlit.)

## Architecture-Specific Images

We build **separate Docker images per CPU architecture** rather than using multi-arch manifests. This was a deliberate decision after running into persistent issues with multi-architecture builds — particularly around numpy and compiled scientific libraries.

- `Dockerfile.arm64` — targets macOS (Apple Silicon) development machines
- `Dockerfile.amd64` — targets Linux cloud VMs and CI environments

Both Dockerfiles are functionally identical in terms of application setup. The differences are limited to the base image tag and any architecture-specific build flags for compiled dependencies.

### Building

```bash
# On an ARM64 Mac (local development)
docker compose -f docker-compose.arm64.yml build
docker compose -f docker-compose.arm64.yml up

# On an AMD64 Linux VM (staging / production)
docker compose -f docker-compose.amd64.yml build
docker compose -f docker-compose.amd64.yml up
```

## Docker Compose Structure

Each Compose file defines the same four services. Here's a simplified view of the service definitions:

```yaml
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile.<arch>
    command: uvicorn backend.main:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    depends_on:
      - redis
    volumes:
      - ./data:/app/data

  worker:
    build:
      context: .
      dockerfile: Dockerfile.<arch>
    command: celery -A backend.celery_worker worker --loglevel=info
    depends_on:
      - redis
    volumes:
      - ./data:/app/data
      - ./results:/app/results

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  frontend:
    build:
      context: .
      dockerfile: Dockerfile.<arch>
    command: streamlit run frontend/app.py --server.port 8501 --server.address 0.0.0.0
    ports:
      - "8501:8501"
    depends_on:
      - api
```

## Key Dependency: numpy 1.x

The `requirements.txt` (and its hashed lockfile) pins numpy to the 1.x series. numpy 2.x introduced breaking changes that affect GPy and scipy, both of which are critical to the surrogate modeling component inside the SACE framework. This pin is enforced at build time and should not be overridden.

## Volumes and Persistence

| Volume Mount | Purpose |
|---|---|
| `./data:/app/data` | SQLite database — shared between the API and worker so both can read/write job records |
| `./results:/app/results` | SACE output files — written by the worker, accessible for download or analysis |

These mounts ensure that job data and optimization results persist across container restarts and rebuilds.

## Design Decisions

**Why not multi-arch builds?**
Multi-architecture Docker builds (via `docker buildx`) caused intermittent failures during compilation of numpy, scipy, and GPy wheels. Building natively on each target architecture is slower in CI but avoids flaky cross-compilation entirely.

**Why HTTP polling instead of WebSockets?**
Streamlit's execution model reruns the entire script on interaction, which makes persistent WebSocket connections fragile. A simple HTTP polling loop (~2s interval) against the FastAPI status endpoint is more reliable and straightforward to maintain.

**Why SQLite?**
For the current scale of the project, SQLite provides zero-config persistence without introducing another networked service. The API and worker share the database file through a Docker volume. If the project needed concurrent write-heavy workloads, PostgreSQL would be the natural upgrade path.

**Why is validation done twice?**
Config validation runs both in the API layer (before persisting) and again in the Celery worker (before invoking SACE). This defense-in-depth approach ensures that even if a job somehow enters the queue with a bad config — through a bug, a race condition, or a future code change — the SACE framework never receives unvalidated input.