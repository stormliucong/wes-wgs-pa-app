# Build a lightweight Flask app image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy source
COPY . .

# Expose port and run with gunicorn; bind to $PORT if provided
EXPOSE 8080
CMD ["sh", "-c", "gunicorn -w 2 -b 0.0.0.0:${PORT:-8080} app.main:app"]
