#!/usr/bin/env bash
# Instala dependencias y verifica la configuración del pipeline.
set -euo pipefail
cd "$(dirname "$0")"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
fail() { echo -e "${RED}✘${NC} $*"; }

# 1. Python >= 3.11
PY=${PYTHON:-python3}
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  fail "Se requiere Python >= 3.11 (encontrado: $("$PY" --version 2>&1))"; exit 1
fi
ok "Python $("$PY" --version | cut -d' ' -f2)"

# 2. Entorno virtual + dependencias
if [[ ! -d .venv ]]; then "$PY" -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "Dependencias instaladas en .venv"

# 3. Archivo .env
if [[ ! -f .env ]]; then
  cp .env.example .env
  warn "Se creó .env a partir de .env.example — complétalo y vuelve a ejecutar ./setup.sh"
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

# 4. Variables obligatorias
missing=0
for var in ANTHROPIC_API_KEY VERCEL_TOKEN EVOLUTION_API_KEY; do
  val="${!var:-}"
  if [[ -z "$val" || "$val" == "sk-ant-..." ]]; then
    fail "$var no está definida"; missing=1
  else
    ok "$var definida"
  fi
done
if [[ -z "${GOOGLE_MAPS_API_KEY:-}" ]]; then
  warn "GOOGLE_MAPS_API_KEY vacía: sólo podrás usar --source gosom/omkarcloud/file"
else
  ok "GOOGLE_MAPS_API_KEY definida"
fi

# 5. Evolution API (opcional en este punto)
EVO_URL="${EVOLUTION_API_URL:-http://localhost:8080}"
if command -v curl >/dev/null && curl -fsS -m 5 -H "apikey: ${EVOLUTION_API_KEY:-}" "$EVO_URL/instance/fetchInstances" >/dev/null 2>&1; then
  ok "Evolution API responde en $EVO_URL"
else
  warn "Evolution API no responde en $EVO_URL (levántala con: docker compose --env-file .env up -d)"
fi

# 6. Tests rápidos
if python -m pytest -q >/dev/null 2>&1; then ok "Tests unitarios OK"; else warn "Algunos tests fallaron (python -m pytest -q)"; fi

if [[ $missing -ne 0 ]]; then
  fail "Faltan variables obligatorias en .env"; exit 1
fi
ok "Todo listo. Ejemplo: source .venv/bin/activate && python main.py --niche barberías --location Puebla --limit 15 --dry-run"
