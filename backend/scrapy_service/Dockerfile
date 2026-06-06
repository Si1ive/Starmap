# StarMap Scrapy Service Dockerfile
# Supports both Docker and Podman

FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    LOG_LEVEL=INFO

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 scrapy && \
    chown -R scrapy:scrapy /app
USER scrapy

# Expose port (for health checks if needed)
EXPOSE 6800

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import scrapy; print('OK')" || exit 1

# Default command: run in consumer mode
CMD ["python", "main.py", "--mode", "consumer"]
