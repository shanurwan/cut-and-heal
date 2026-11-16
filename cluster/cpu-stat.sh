#!/usr/bin/env bash
# Snapshot the cgroup CPU counters of each region node container: `cpu-stat.sh start|end <dir>`.
# The report compares the two to give cores used and the share of periods spent throttled,
# which the host-wide load sampler cannot see when a node has its own cap.
set -euo pipefail
NAME="${CAH_CLUSTER:-cah}"
WHEN="${1:?usage: $0 start|end <dir>}"
DIR="${2:?usage: $0 start|end <dir>}"
mkdir -p "$DIR"
if [ "$WHEN" = start ]; then
  { echo "$(nproc) CPUs,"; lscpu | sed -n "s/^Model name: *//p" | head -1; echo ", kernel $(uname -r)"; } >"$DIR/host.txt"
fi
for node in $(docker ps --format '{{.Names}}' --filter "network=$NAME" | grep -v -- "-control$"); do
  id="$(docker inspect -f '{{.Id}}' "$node")"
  stat="$(find /sys/fs/cgroup -maxdepth 4 -type d -name "*$id*" 2>/dev/null | head -1)/cpu.stat"
  if [ -r "$stat" ]; then
    { echo "wall_ns $(date +%s%N)"; cat "$stat"; } >"$DIR/$node.cpu.$WHEN"
  else
    echo "no cgroup cpu.stat found for $node" >&2
  fi
done
