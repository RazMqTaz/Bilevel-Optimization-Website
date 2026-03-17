#!/bin/bash
set -e

echo "=== Building backend ==="

docker build --platform linux/arm64 -t backend:arm64 -f backend/Dockerfile .
docker build --platform linux/amd64 -t backend:amd64 -f backend/Dockerfile .

echo "=== Tagging backend ==="

docker tag backend:arm64 razmqtaz/backend:latest-arm64
docker tag backend:amd64 razmqtaz/backend:latest-amd64

echo "=== Pushing backend ==="

docker push razmqtaz/backend:latest-arm64
docker push razmqtaz/backend:latest-amd64

echo ""
echo "=== Building frontend ==="

docker build --platform linux/arm64 -t frontend:arm64 -f frontend/Dockerfile .
docker build --platform linux/amd64 -t frontend:amd64 -f frontend/Dockerfile .

echo "=== Tagging frontend ==="

docker tag frontend:arm64 razmqtaz/frontend:latest-arm64
docker tag frontend:amd64 razmqtaz/frontend:latest-amd64

echo "=== Pushing frontend ==="

docker push razmqtaz/frontend:latest-arm64
docker push razmqtaz/frontend:latest-amd64

echo ""
echo "=== Done ==="
echo "On the VM, run:"
echo "  docker compose pull"
echo "  docker compose up -d"