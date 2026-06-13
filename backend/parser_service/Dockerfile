FROM python:3.11-slim

ARG PARSER_FLAVOR=mineru
ARG MINERU_PACKAGE_SPEC=mineru[all]>=3.3,<4
ARG DOCLING_PACKAGE_SPEC=docling>=2.0.0

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    cmake \
    build-essential \
    libglib2.0-0 \
    libgl1 \
    libmagic1 \
    libjpeg62-turbo \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

COPY parser_service/requirements.txt /tmp/parser_service_requirements.txt
RUN pip install --no-cache-dir -r /tmp/parser_service_requirements.txt && \
    if [ "$PARSER_FLAVOR" = "mineru" ]; then \
      pip install --no-cache-dir "$MINERU_PACKAGE_SPEC"; \
    elif [ "$PARSER_FLAVOR" = "docling" ]; then \
      pip install --no-cache-dir "$DOCLING_PACKAGE_SPEC"; \
    elif [ "$PARSER_FLAVOR" = "both" ]; then \
      pip install --no-cache-dir "$DOCLING_PACKAGE_SPEC" "$MINERU_PACKAGE_SPEC"; \
    else \
      echo "Unsupported PARSER_FLAVOR: $PARSER_FLAVOR" && exit 1; \
    fi

COPY app /app/app
COPY parser_service /app/parser_service
RUN chmod +x /app/parser_service/start.sh

EXPOSE 8090

CMD ["/app/parser_service/start.sh"]
