Create venv

# install requirements.txt, both in the root and in the SACEProject folder

# run
streamlit run frontend/app.py

# To run the backend:
uvicorn backend.main:app --reload

(It might prompt you to install more dependencies not sure, the dockerfiles automatically install them so requirements.txt is probably out of date.


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