Create venv

# install streamlit
pip install streamlit

# run
streamlit run backend/app.py

# To run the backend:
uvicorn backend.main:app --reload