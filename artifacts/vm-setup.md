# VM Setup Guide

This document walks through how to set up a fresh virtual machine to run the SACE framework application stack. It covers system dependencies, Python environment setup, service configuration, and verification steps.

## Prerequisites

- A Linux-based VM (Ubuntu 22.04 LTS recommended)
- At least 2 vCPUs, 4 GB RAM, and 20 GB disk space
- SSH access with sudo privileges
- Ports 8000 (API), 8501 (Streamlit), and 6379 (Redis) available

## 1. System Dependencies

Start by updating the package index and installing the base tooling:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.10 python3.10-venv python3-pip git curl build-essential
```

Redis is used as the message broker for Celery. Install it from the default repos:

```bash
sudo apt install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

Confirm Redis is running:

```bash
redis-cli ping
# Expected output: PONG
```

## 2. Clone the Repository

```bash
git clone https://github.com/<your-org>/<your-repo>.git
cd <your-repo>
```

Replace the URL and directory name with your actual GitHub repository.

## 3. Python Virtual Environment

We use a virtual environment to isolate project dependencies and avoid conflicts with system packages.

```bash
python3.10 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> **Note:** numpy is pinned to 1.x in `requirements.txt` due to compatibility issues with GPy and scipy. Do not upgrade numpy to 2.x — it will break the surrogate modeling pipeline.

## 4. Environment Variables

Create a `.env` file in the project root (or export these in your shell session):

```bash
# .env
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=sqlite:///./sace.db
```

The application reads these at startup. Adjust values if your Redis instance is hosted elsewhere or if you want the SQLite database in a different location.

## 5. Starting the Services

The application has three main processes that need to run. In a development setup, the easiest approach is to use separate terminal sessions (or tmux/screen panes).

### FastAPI Backend

```bash
source venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### Celery Worker

```bash
source venv/bin/activate
celery -A backend.celery_worker worker --loglevel=info
```

### Streamlit Frontend

```bash
source venv/bin/activate
streamlit run frontend/app.py --server.port 8501 --server.address 0.0.0.0
```

## 6. Verifying the Setup

Once all three services are running:

1. **API health check** — Visit `http://<vm-ip>:8000/docs` in a browser. You should see the FastAPI interactive documentation (Swagger UI).
2. **Frontend** — Navigate to `http://<vm-ip>:8501`. The Streamlit dashboard should load and be able to submit optimization jobs.
3. **Celery** — Check the Celery worker terminal for log output. Submitting a job through the frontend should produce task pickup and execution logs.

## 7. Running as Background Services (Optional)

For longer-running or production-like deployments, you can daemonize the processes using systemd unit files or a process manager like `supervisord`. A simpler option for development is to run everything inside a `tmux` session so processes persist after disconnecting from SSH.

Example with tmux:

```bash
sudo apt install -y tmux
tmux new-session -s sace

# Pane 1: API
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Ctrl+B, % to split — Pane 2: Celery
celery -A backend.celery_worker worker --loglevel=info

# Ctrl+B, % to split — Pane 3: Streamlit
streamlit run frontend/app.py --server.port 8501 --server.address 0.0.0.0
```

Detach with `Ctrl+B, D` and reattach later with `tmux attach -t sace`.

## Troubleshooting

| Problem | Likely Cause | Fix |
|---|---|---|
| `redis.exceptions.ConnectionError` | Redis not running | `sudo systemctl start redis-server` |
| `ModuleNotFoundError` | Virtual environment not activated | `source venv/bin/activate` |
| numpy/GPy import errors | numpy 2.x installed | Pin numpy to 1.x: `pip install "numpy<2"` |
| Streamlit won't load in browser | Port 8501 blocked by firewall | Open the port: `sudo ufw allow 8501` |
| Celery worker hangs on startup | Wrong broker URL | Verify `REDIS_URL` in `.env` matches your Redis instance |