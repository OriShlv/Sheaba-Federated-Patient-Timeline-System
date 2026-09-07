#!/bin/bash

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"

echo "🚀 Starting Sheebah Patient Timeline System..."

if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 is required. Install Python 3.12 or newer and try again."
    exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
    echo "❌ Python 3.12 or newer is required."
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

echo "📦 Starting infrastructure services (Postgres, MongoDB, Redis, Mock Vitals, Frontend)..."
cd "$ROOT_DIR"
echo "⏳ Waiting for services to be ready..."
if ! docker compose up -d --wait --wait-timeout 120; then
    echo "❌ Required Docker services did not become healthy within 120 seconds."
    exit 1
fi

echo "🌱 Seeding MongoDB..."
if ! docker exec -i sheebah-timeline-mongodb mongosh pacs --quiet \
    < infra/mongodb/seed-manual.js; then
    echo "❌ MongoDB seeding failed."
    exit 1
fi

echo "🔍 Checking service health..."
docker compose ps

if [ ! -d "$VENV_DIR" ]; then
    echo "🐍 Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if ! python -c "import timeline_api" >/dev/null 2>&1; then
    echo "📦 Installing backend dependencies (first run only)..."
    python -m pip install -e "$BACKEND_DIR[dev]"
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo "⚙️  Creating backend/.env from .env.example..."
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
fi

echo ""
echo "✅ Infrastructure is ready!"
echo ""
echo "🌐 Services:"
echo "   - Frontend:    http://localhost:5173"
echo "   - Backend API: http://localhost:3000"
echo "   - API Docs:    http://localhost:3000/docs"
echo "   - Mock Vitals: http://localhost:3001"
echo ""
echo "🚀 Starting backend (Ctrl+C stops the backend only)"
echo "🛑 Stop Docker services later with: docker compose down"
echo ""

cd "$BACKEND_DIR"
export PYTHONPATH=src
exec uvicorn timeline_api.main:app --reload --host 0.0.0.0 --port 3000
