#!/bin/bash

# Update running stack: log into Azure ACR, pull images, restart services.
# Run from the directory that contains docker-compose.prod.eleven.yml (e.g. /opt/onyx after copying deployment/azure-vm).
# Requires: ACR_REGISTRY set in .env (e.g. myregistry.azurecr.io). Azure CLI and login to Azure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f "docker-compose.prod.eleven.yml" ]; then
  echo "Error: docker-compose.prod.eleven.yml not found in $SCRIPT_DIR" >&2
  exit 1
fi

# Load ACR_REGISTRY from .env if present
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

if [ -z "${ACR_REGISTRY:-}" ]; then
  echo "Error: ACR_REGISTRY not set. Set it in .env or environment (e.g. myregistry.azurecr.io)." >&2
  exit 1
fi

# Registry name is the first component (without .azurecr.io)
ACR_NAME="${ACR_REGISTRY%%.*}"

echo "=== Updating Eleven stack ==="
echo "Registry: $ACR_REGISTRY"
echo "Compose file: docker-compose.prod.eleven.yml"

echo "Logging into ACR..."
az acr login --name "$ACR_NAME"

echo "Pulling images..."
docker compose -f docker-compose.prod.eleven.yml pull

echo "Restarting services..."
docker compose -f docker-compose.prod.eleven.yml up -d --remove-orphans

echo "Cleaning up old images..."
docker image prune -f

echo "=== Running containers ==="
docker compose -f docker-compose.prod.eleven.yml ps

echo "=== Update complete ==="
