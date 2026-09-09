#!/bin/bash

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "♻️  Resetting PACS imaging data to the assignment seed..."
echo "   This deletes all documents in pacs.imaging, then reloads the supplied seed."

if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

if ! docker inspect -f '{{.State.Running}}' sheebah-timeline-mongodb 2>/dev/null | grep -q true; then
    echo "❌ MongoDB is not running. Start infrastructure with ./start.sh first."
    exit 1
fi

if ! docker exec -i sheebah-timeline-mongodb mongosh pacs --quiet \
    < "$ROOT_DIR/infra/mongodb/seed-manual.js"; then
    echo "❌ MongoDB reset failed."
    exit 1
fi

echo "✅ PACS imaging collection restored to the assignment seed."
