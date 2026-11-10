#!/usr/bin/env bash
# Build the controller image and import it into every cluster node, so a run needs no registry.
set -euo pipefail
NAME="${CAH_CLUSTER:-cah}"
IMAGE="${1:?usage: $0 <image:tag>}"
docker build -q -t "$IMAGE" "$(dirname "$0")/.." >/dev/null
for node in $(docker ps --format '{{.Names}}' --filter "network=$NAME"); do
  docker save "$IMAGE" | docker exec -i "$node" ctr -n k8s.io images import - >/dev/null
  echo "imported $IMAGE into $node"
done
