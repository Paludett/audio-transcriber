#!/usr/bin/env bash
# Sobe a API (uvicorn) e abre o frontend no browser padrão, num único comando.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f "venv/bin/activate" ]; then
    echo "venv não encontrada. Rode a instalação do README primeiro:" >&2
    echo "  python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt" >&2
    exit 1
fi

# shellcheck disable=SC1091
source venv/bin/activate

uvicorn backend.main:app --reload &
UVICORN_PID=$!

cleanup() {
    # --reload spawns a worker subprocess; kill the whole process group so it dies too.
    # The reloader sometimes logs "stopping" without actually exiting, so force-kill
    # any survivor after a short grace period to make sure port 8000 is freed.
    kill -TERM -- "-$UVICORN_PID" 2>/dev/null || true
    sleep 1
    kill -KILL -- "-$UVICORN_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Aguardando API subir em http://localhost:8000 ..."
for _ in $(seq 1 60); do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        echo "API pronta."
        break
    fi
    sleep 0.5
done

if ! curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo "API não respondeu em 30s. Veja os logs do uvicorn acima." >&2
    exit 1
fi

INDEX_PATH="file://$(pwd)/frontend/index.html"
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$INDEX_PATH" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then
    open "$INDEX_PATH" &
else
    echo "Abra manualmente: $INDEX_PATH"
fi

wait "$UVICORN_PID"
