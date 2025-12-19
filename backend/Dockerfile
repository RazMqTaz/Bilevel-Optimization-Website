FROM python:3.9-slim

WORKDIR /app

# Install system dependencies for building packages like GPy and numpy/scipy
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libopenblas-dev \
    liblapack-dev \
    gfortran \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY SACEProject/ ./SACEProject/
COPY backend/ ./backend/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir numpy scipy GPy tqdm matplotlib scikit-learn pandas

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
