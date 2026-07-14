#!/usr/bin/env sh
set -eu

HOST="${PARSER_SERVICE_HOST:-0.0.0.0}"
PORT="${PARSER_SERVICE_PORT:-8090}"
export MINERU_TOOLS_CONFIG_JSON="${MINERU_TOOLS_CONFIG_JSON:-/root/.cache/mineru/mineru.json}"
mkdir -p "$(dirname "${MINERU_TOOLS_CONFIG_JSON}")"

if [ -z "${MINERU_MODEL_SOURCE:-}" ]; then
  if [ -f "${MINERU_TOOLS_CONFIG_JSON}" ]; then
    export MINERU_MODEL_SOURCE="local"
  else
    export MINERU_MODEL_SOURCE="modelscope"
  fi
fi

export MINERU_PDF_RENDER_THREADS="${MINERU_PDF_RENDER_THREADS:-1}"
export MINERU_PDF_RENDER_TIMEOUT="${MINERU_PDF_RENDER_TIMEOUT:-600}"
export MINERU_PROCESSING_WINDOW_SIZE="${MINERU_PROCESSING_WINDOW_SIZE:-1}"

echo "[parser-service] starting MinerU on ${HOST}:${PORT}, model_source=${MINERU_MODEL_SOURCE}, config_json=${MINERU_TOOLS_CONFIG_JSON}, render_threads=${MINERU_PDF_RENDER_THREADS}, render_timeout=${MINERU_PDF_RENDER_TIMEOUT}, window_size=${MINERU_PROCESSING_WINDOW_SIZE}"

exec uvicorn parser_service.main:app --host "${HOST}" --port "${PORT}"
