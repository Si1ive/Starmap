FROM python:3.11-slim

ARG PARSER_FLAVOR=mineru

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    cmake \
    build-essential \
    libglib2.0-0 \
    libgl1 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY parser_service/requirements.txt /tmp/parser_service_requirements.txt
RUN pip install --no-cache-dir -r /tmp/parser_service_requirements.txt && \
    if [ "$PARSER_FLAVOR" = "mineru" ]; then \
      pip install --no-cache-dir "mineru[core]>=2.0.0"; \
    elif [ "$PARSER_FLAVOR" = "docling" ]; then \
      pip install --no-cache-dir "docling>=2.0.0"; \
    elif [ "$PARSER_FLAVOR" = "both" ]; then \
      pip install --no-cache-dir "docling>=2.0.0" "mineru[core]>=2.0.0"; \
    else \
      echo "Unsupported PARSER_FLAVOR: $PARSER_FLAVOR" && exit 1; \
    fi

COPY app /app/app
COPY parser_service /app/parser_service

EXPOSE 8090

CMD ["uvicorn", "parser_service.main:app", "--host", "0.0.0.0", "--port", "8090"]
