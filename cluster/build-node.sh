#!/usr/bin/env bash
# Build the regression node from its source with one change, and import it into every
# cluster node, for scenarios that set `node.image`.
#
# The change (cluster/node/yamux-idle-timeout.patch) makes the idle timeout of yamux streams
# a setting, YAMUX_IDLE_TIMEOUT_S, which the library already takes as a parameter. Left
# unset, the node behaves as the published one. Source, commit and Dockerfile are the DST
# team's own; nothing else differs.
set -euo pipefail
NAME="${CAH_CLUSTER:-cah}"
IMAGE="${1:?usage: $0 <image:tag>}"
REPO="https://github.com/iftech/dst-libp2p-test-node"
COMMIT="fb8691ebe5c54b19926ed3ffbc4de20783429ddf"
HERE="$(cd "$(dirname "$0")" && pwd)"

SRC="$(mktemp -d)"
trap 'rm -rf "$SRC"' EXIT
git clone -q "$REPO" "$SRC"
git -C "$SRC" checkout -q "$COMMIT"
git -C "$SRC" apply "$HERE/node/yamux-idle-timeout.patch"
docker build -q -f "$SRC/nim-test-node/regression/Dockerfile" --build-arg NODE_BINARY=node \
  -t "$IMAGE" "$SRC/nim-test-node/regression" >/dev/null
echo "built $IMAGE from $REPO at $COMMIT with yamux-idle-timeout.patch"

for node in $(docker ps --format '{{.Names}}' --filter "network=$NAME"); do
  docker save "$IMAGE" | docker exec -i "$node" ctr -n k8s.io images import - >/dev/null
  echo "imported $IMAGE into $node"
done
