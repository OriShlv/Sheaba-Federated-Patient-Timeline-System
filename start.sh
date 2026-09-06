#!/bin/bash

set -e

echo "🚀 Starting Sheebah Patient Timeline System..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

# Start infrastructure services
echo "📦 Starting infrastructure services (Postgres, MongoDB, Redis, Mock Vitals, Frontend)..."
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 15

# Seed MongoDB if needed
echo "🌱 Seeding MongoDB..."
docker exec -i sheebah-timeline-mongodb mongosh pacs --quiet < infra/mongodb/seed-manual.js || echo "MongoDB seeding completed or already seeded"

# Check if services are healthy
echo "🔍 Checking service health..."
docker-compose ps

echo ""
echo "✅ All services are running!"
echo ""
echo "📋 Next steps:"
echo "   1. Start the backend manually: cd backend && PYTHONPATH=src uvicorn timeline_api.main:app --reload --port 3000"
echo ""
echo "🌐 Services will be available at:"
echo "   - Frontend: http://localhost:5173"
echo "   - Backend API: http://localhost:3000 (when backend is running)"
echo "   - API Docs: http://localhost:3000/docs (when backend is running)"
echo "   - Mock Vitals: http://localhost:3001"
echo ""
echo "🛑 To stop all services: docker-compose down"
