FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create workspace directories
RUN mkdir -p workspace/logs workspace/data

ENV PYTHONUNBUFFERED=1

# Health check: poll HTTP health endpoint
HEALTHCHECK --interval=60s --timeout=10s --retries=3 --start-period=30s \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python3", "scripts/trading_engine.py"]
