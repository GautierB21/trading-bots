FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir flask gunicorn pandas-ta

# Copy application
COPY . .

# Create data directory for SQLite
RUN mkdir -p data

# Expose port
ENV PORT=8080
EXPOSE 8080

# Single worker: the intraday scheduler is an in-process singleton (in-memory
# cash/positions + a Kraken WS connection). With >1 worker, each worker
# imports server.py independently and starts its own scheduler instance,
# duplicating every trade against the same DB. --threads keeps concurrency
# for the Flask API without spawning a second worker process.
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 server:app
