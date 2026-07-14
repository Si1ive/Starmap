FROM python:3.11-slim

ARG MINERU_PACKAGE_SPEC=mineru[pipeline]>=3.3,<4
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG TORCH_PACKAGE_SPEC=torch==2.12.0+cpu
ARG TORCHVISION_PACKAGE_SPEC=torchvision==0.27.0+cpu

WORKDIR /app

COPY parser_service/requirements.txt /tmp/parser_service_requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends \
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
    && pip install --no-cache-dir -r /tmp/parser_service_requirements.txt && \
    pip install --no-cache-dir --index-url "$TORCH_INDEX_URL" "$TORCH_PACKAGE_SPEC" "$TORCHVISION_PACKAGE_SPEC" && \
    pip install --no-cache-dir "$MINERU_PACKAGE_SPEC" six && \
    apt-get purge -y --auto-remove \
      gcc \
      g++ \
      cmake \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY app /app/app
COPY parser_service /app/parser_service
RUN chmod +x /app/parser_service/start.sh

EXPOSE 8090

CMD ["/app/parser_service/start.sh"]
