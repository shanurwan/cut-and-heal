#!/usr/bin/env bash
# Remove the cluster created by cluster/up.sh. Touches only containers on its own network.
set -euo pipefail
NAME="${CAH_CLUSTER:-cah}"
nodes="$(docker ps -aq --filter "network=$NAME")"
[ -z "$nodes" ] || docker rm -f -v $nodes >/dev/null
docker network rm "$NAME" >/dev/null 2>&1 || true
rm -f "${CAH_KUBE_DIR:-$PWD/.kube}/kubeconfig.yaml"
echo "cluster $NAME removed"
