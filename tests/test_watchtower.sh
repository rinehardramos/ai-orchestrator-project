#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# test_watchtower.sh — Verifies that Watchtower correctly pulls updated images.
#
# This script:
# 1. Starts a local Docker registry.
# 2. Pushes an initial version of an image to the registry.
# 3. Starts a container using that image, and Watchtower to monitor it.
# 4. Pushes a new version of the image to the registry.
# 5. Waits and verifies that Watchtower pulled the new image and restarted the container.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

log() { echo -e "\n---> $1"; }
error() { echo -e "\n[ERROR] $1" >&2; exit 1; }

# Check for docker
if ! command -v docker >/dev/null 2>&1; then
  error "Docker is not installed or not in PATH."
fi

REGISTRY_NAME="test-registry"
REGISTRY_PORT="5000"
IMAGE_NAME="localhost:${REGISTRY_PORT}/watchtower-test-app"
CONTAINER_NAME="test-app"
WATCHTOWER_NAME="test-watchtower"

cleanup() {
  log "Cleaning up test containers..."
  docker rm -f "$WATCHTOWER_NAME" "$CONTAINER_NAME" "$REGISTRY_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup

log "Starting local Docker registry..."
docker run -d -p "$REGISTRY_PORT:5000" --name "$REGISTRY_NAME" registry:2

log "Building and pushing Version 1 of the image (alpine:3.18)..."
echo -e "FROM alpine:3.18\nCMD [\"tail\", \"-f\", \"/dev/null\"]" > Dockerfile.v1
docker build -t "${IMAGE_NAME}:latest" -f Dockerfile.v1 .
docker push "${IMAGE_NAME}:latest"
rm Dockerfile.v1

log "Starting the test application container..."
docker run -d --name "$CONTAINER_NAME" "${IMAGE_NAME}:latest"

INITIAL_IMAGE_ID=$(docker inspect --format='{{.Image}}' "$CONTAINER_NAME")
log "Initial App Image ID: $INITIAL_IMAGE_ID"

log "Starting Watchtower to monitor the test application (polling every 5s)..."
docker run -d --name "$WATCHTOWER_NAME" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower:1.7.1 \
  --interval 5 --cleanup "$CONTAINER_NAME"

log "Waiting for 10 seconds to ensure Watchtower has initialized..."
sleep 10

log "Building and pushing Version 2 of the image (alpine:3.19)..."
echo -e "FROM alpine:3.19\nCMD [\"tail\", \"-f\", \"/dev/null\"]" > Dockerfile.v2
docker build -t "${IMAGE_NAME}:latest" -f Dockerfile.v2 .
docker push "${IMAGE_NAME}:latest"
rm Dockerfile.v2

log "Waiting for Watchtower to detect the update and restart the container (approx 15-20s)..."
for i in {1..6}; do
  sleep 5
  CURRENT_IMAGE_ID=$(docker inspect --format='{{.Image}}' "$CONTAINER_NAME")
  if [ "$CURRENT_IMAGE_ID" != "$INITIAL_IMAGE_ID" ]; then
    log "SUCCESS: Watchtower successfully pulled the updated image and restarted the container!"
    log "Old Image ID: $INITIAL_IMAGE_ID"
    log "New Image ID: $CURRENT_IMAGE_ID"
    exit 0
  fi
  echo "Still waiting... ($((i * 5))s)"
done

error "Watchtower did not update the container within the expected timeframe."
