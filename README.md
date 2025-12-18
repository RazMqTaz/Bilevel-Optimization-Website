Create venv

# install streamlit
pip install streamlit

# run
streamlit run frontend/app.py

# To run the backend:
uvicorn backend.main:app --reload


# To run Docker:
1. Install Docker on your device (recommend docker desktop)
2. Enable docker extension in your IDE
3. To compose the docker system:
    3a. docker compose up --build
it should show up in your docker desktop

To push new build to backend-latest: 

`docker build -t razmqtaz/backend:latest -f backend/Dockerfile .`
