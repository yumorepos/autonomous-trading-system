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

# Health check: verify heartbeat is fresh
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python3 scripts/trading_engine.py --status || exit 1

CMD ["python3", "scripts/trading_engine.py"]
