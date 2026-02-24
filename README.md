## Local setup (no Docker)

### 1. Create a virtual environment and install dependencies

Using the project venv ensures the backend and frontend use the same Python that has FastAPI, uvicorn, etc. (If you run `uvicorn` from pipx, it uses a different Python and will fail with "No module named 'fastapi'".)

```bash
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -e .
```

Or install from the full lockfile:

```bash
pip install -r requirements.txt
```

### 2. Run the frontend

```bash
streamlit run frontend/app.py
```

### 3. Run the backend

Use the **same** Python as the one where you installed packages (the venv), so that uvicorn can see FastAPI:

```bash
python -m uvicorn backend.main:app --reload
```

Or use the helper script (creates `.venv` and installs deps if needed, then runs the backend):

```bash
./run_backend.sh
```

(It might prompt you to install more dependencies; the Dockerfiles install them automatically so `requirements.txt` may be slightly out of date.)


# To run Docker:
1. Install Docker on your device (recommend docker desktop)
2. Enable docker extension in your IDE
3. In your compose.yaml folder, edit the image line for frontend and backend to either latest-arm64 or latest-amd64 depending on your OS (arm64 for Apple Silicon devices and amd64 for Linux)
4. To compose the docker system:
    3a. docker compose up --build

# Docker Info
## Backend
### To build new image in platform specific

docker build --platform linux/arm64 -t backend:arm64 -f backend/Dockerfile .
docker build --platform linux/amd64 -t backend:amd64 -f backend/Dockerfile .

### Tag Images
docker tag backend:arm64 razmqtaz/backend:latest-arm64
docker tag backend:amd64 razmqtaz/backend:latest-amd64

### Push images
docker push razmqtaz/backend:latest-arm64
docker push razmqtaz/backend:latest-amd64

## Frontend
### To build new image in platform specific
docker build --platform linux/arm64 -t frontend:arm64 -f frontend/Dockerfile .
docker build --platform linux/amd64 -t frontend:amd64 -f frontend/Dockerfile .

### Tag Images
docker tag frontend:arm64 razmqtaz/frontend:latest-arm64
docker tag frontend:amd64 razmqtaz/frontend:latest-amd64

### Push Images
docker push razmqtaz/frontend:latest-arm64
docker push razmqtaz/frontend:latest-amd64