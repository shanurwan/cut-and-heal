#!/usr/bin/env bash
# Create a K3s cluster in Docker with one Kubernetes node per region.
#
#   cluster/up.sh ir world        # a control node plus one node for each region
#
# Regions are Kubernetes nodes on purpose: each node owns a pod CIDR, so every region's pods
# share an address range that tc can match. A lab with real machines gets the same thing by
# labelling its nodes `cut-and-heal/region=<name>`; nothing else in the tool depends on Docker.
set -euo pipefail

NAME="${CAH_CLUSTER:-cah}"
K3S_IMAGE="${CAH_K3S_IMAGE:-rancher/k3s:v1.32.4-k3s1}"
MAX_PODS="${CAH_MAX_PODS:-400}"
API_PORT="${CAH_API_PORT:-6550}"
OUT="${CAH_KUBE_DIR:-$PWD/.kube}"
REGIONS=("$@")
[ "${#REGIONS[@]}" -ge 2 ] || { echo "usage: $0 <region> <region> [...]" >&2; exit 2; }

# A /23 per node holds 510 pods; the default /24 caps a region at 254 whatever max-pods says.
# TCP timers are per network namespace, so a pod may set its own. Nothing wider is allowed.
COMMON=(--kubelet-arg="max-pods=${MAX_PODS}" --kubelet-arg="allowed-unsafe-sysctls=net.ipv4.tcp_*")
if docker info --format '{{.SecurityOptions}}' | grep -q rootless; then
  # Rootless Docker needs the cpu, cpuset and io cgroup controllers delegated to the user;
  # without them K3s exits with "failed to find cpu cgroup (v2)".
  COMMON+=(--kubelet-arg="feature-gates=KubeletInUserNamespace=true")
fi

TOKEN="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
mkdir -p "$OUT"
docker network inspect "$NAME" >/dev/null 2>&1 || docker network create "$NAME" >/dev/null

run_node() { # name, then k3s arguments
  local node="$1"; shift
  docker run -d --name "$node" --hostname "$node" --network "$NAME" \
    --privileged --tmpfs /run --tmpfs /var/run \
    --ulimit nofile=1048576:1048576 \
    -e K3S_TOKEN="$TOKEN" "${EXTRA_DOCKER[@]}" "$K3S_IMAGE" "$@" >/dev/null
}

EXTRA_DOCKER=(-p "127.0.0.1:${API_PORT}:6443" -v "$OUT:/output" -e K3S_KUBECONFIG_OUTPUT=/output/kubeconfig.yaml -e K3S_KUBECONFIG_MODE=644)
run_node "$NAME-control" server \
  --disable=traefik --disable=servicelb --disable=metrics-server \
  --tls-san=127.0.0.1 \
  --cluster-cidr=10.42.0.0/16 \
  --kube-controller-manager-arg=node-cidr-mask-size-ipv4=23 \
  --node-label=cut-and-heal/control=true \
  "${COMMON[@]}"

EXTRA_DOCKER=(-e K3S_URL="https://$NAME-control:6443")
for region in "${REGIONS[@]}"; do
  run_node "$NAME-$region" agent --node-label="cut-and-heal/region=$region" "${COMMON[@]}"
done

for _ in $(seq 1 60); do [ -s "$OUT/kubeconfig.yaml" ] && break; sleep 2; done
[ -s "$OUT/kubeconfig.yaml" ] || { echo "the control node wrote no kubeconfig; see: docker logs $NAME-control" >&2; exit 1; }
sed -i "s#https://127.0.0.1:6443#https://127.0.0.1:${API_PORT}#" "$OUT/kubeconfig.yaml"
export KUBECONFIG="$OUT/kubeconfig.yaml"

want=$((${#REGIONS[@]} + 1))
for _ in $(seq 1 90); do
  ready="$(kubectl get nodes --no-headers 2>/dev/null | awk '$2 == "Ready"' | wc -l)"
  [ "$ready" -eq "$want" ] && break
  sleep 2
done
kubectl get nodes -L cut-and-heal/region,cut-and-heal/control -o wide
[ "$ready" -eq "$want" ] || { echo "only $ready of $want nodes are Ready" >&2; exit 1; }
kubectl get nodes -o custom-columns='NODE:.metadata.name,POD_CIDR:.spec.podCIDR'
echo "export KUBECONFIG=$OUT/kubeconfig.yaml"
