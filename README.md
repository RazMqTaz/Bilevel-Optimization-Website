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


To push new build to backend-latest: 

`docker build -t razmqtaz/backend:latest -f backend/Dockerfile .`
