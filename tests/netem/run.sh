#!/usr/bin/env bash
# Kernel-level test of the shaping mechanism. Needs Docker and nothing else.
#
# Three real gossipsub nodes, each with the real shaper sidecar script, on one Docker network
# split into an "inside" and an "outside" address range. A controller serves them the plan
# that plan.py compiles. The test then asks the kernel, not the plan, what happened:
#
#   baseline  everyone reaches everyone; the border adds its delay, domestic links do not
#   cut       nothing crosses the border in either direction; inside still reaches inside
#   bridge    exactly the one open node crosses; the closed one still cannot
#   healed    everyone reaches everyone again
#
# and checks that every shaper acknowledged every phase on schedule.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
P="cah-netem-$$"
SUBNET="${CAH_TEST_SUBNET:-172.31.60}"
NODE_IMAGE="albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988"
BOOT_IMAGE="albertodst/regression-bootstrap-amd64:v.2.4.0@sha256:d136b5f44cfd315a68e2e9680cd2b1eb7489b8566f9bfedba5349046f000d944"
IMAGE="${CAH_TEST_IMAGE:-cut-and-heal:test}"
OUT="$(mktemp -d)"
chmod 777 "$OUT"
FAILED=0

cleanup() {
  if [ "$FAILED" -ne 0 ]; then
    for c in controller inside-0 inside-1 outside-0; do
      echo "--- logs $c"; docker logs "$P-$c" 2>&1 | tail -15 || true
    done
  fi
  docker rm -f "$P-controller" "$P-bootstrap" "$P-inside-0" "$P-inside-1" "$P-outside-0" >/dev/null 2>&1 || true
  docker network rm "$P" >/dev/null 2>&1 || true
  rm -rf "$OUT" 2>/dev/null || true
}
trap cleanup EXIT

declare -A IP=([inside-0]="$SUBNET.10" [inside-1]="$SUBNET.11" [outside-0]="$SUBNET.70")

[ -n "${CAH_TEST_IMAGE:-}" ] || docker build -q -t "$IMAGE" "$ROOT" >/dev/null
docker network create --subnet "$SUBNET.0/24" "$P" >/dev/null
# The controller and bootstrap sit outside both regions' ranges, like a real control plane.
docker run -d --name "$P-controller" --network "$P" --ip "$SUBNET.200" -e CAH_TEST_SUBNET="$SUBNET" \
  -v "$ROOT/tests/netem/controller.py:/test/controller.py:ro" -v "$OUT:/out" \
  --user 0 --entrypoint python "$IMAGE" /test/controller.py >/dev/null
docker run -d --name "$P-bootstrap" --hostname bootstrap-0 --network "$P" --ip "$SUBNET.201" \
  --network-alias bootstrap "$BOOT_IMAGE" >/dev/null
for pod in inside-0 inside-1 outside-0; do
  docker run -d --name "$P-$pod" --hostname "$pod" --network "$P" --ip "${IP[$pod]}" --cap-add NET_ADMIN \
    -e POD_NAME="$pod" -e CAH_CONTROLLER="http://$SUBNET.200:8080" -e SERVICE=bootstrap \
    -v "$ROOT/src/cutandheal/assets/shaper.sh:/shaper/shaper.sh:ro" \
    --entrypoint bash "$NODE_IMAGE" -c '/node/main >/dev/null 2>&1 & exec bash /shaper/shaper.sh' >/dev/null
done

for _ in $(seq 1 90); do [ -s "$OUT/t0" ] && break; sleep 1; done
[ -s "$OUT/t0" ] || { echo "FAIL: the shapers never completed setup"; FAILED=1; exit 1; }
T0="$(cat "$OUT/t0")"
OPEN="$(cat "$OUT/open")"
if [ "$OPEN" = inside-0 ]; then CLOSED=inside-1; else CLOSED=inside-0; fi
echo "T0=$T0, bridging node in the bridge phase: $OPEN"

probe() { # from to -> "<http code> <seconds>"
  docker exec "$P-$1" curl -s -o /dev/null -m 3 -w '%{http_code} %{time_total}' "http://${IP[$2]}:8008/metrics" || true
}
expect() { # phase from to want(open|cut)
  local got code
  got="$(probe "$2" "$3")"; code="${got%% *}"
  if { [ "$4" = open ] && [ "$code" = 200 ]; } || { [ "$4" = cut ] && [ "$code" = 000 ]; }; then
    printf 'ok    %-9s %-10s -> %-10s %-4s (%s)\n' "$1" "$2" "$3" "$4" "$got"
  else
    printf 'FAIL  %-9s %-10s -> %-10s wanted %s, got %s\n' "$1" "$2" "$3" "$4" "$got"; FAILED=1
  fi
}
at() { local wait=$(( T0 + $1 - $(date +%s) )); [ "$wait" -le 0 ] || sleep "$wait"; }

at 10
for pair in "inside-0 outside-0" "outside-0 inside-0" "inside-1 outside-0" "inside-0 inside-1"; do
  expect baseline $pair open
done
# A request is several one-way trips (handshake, request, response): 40 ms each across the
# border, 5 ms each inside a region.
border="$(probe inside-0 outside-0)"; domestic="$(probe inside-0 inside-1)"
awk -v b="${border##* }" -v d="${domestic##* }" 'BEGIN {
  ok = (b >= 0.15 && b < 1.0 && d < 0.10)
  printf "%s  baseline  border round trip %.0f ms (want >= 150), domestic %.0f ms (want < 100)\n", ok ? "ok  " : "FAIL", b*1000, d*1000
  exit !ok }' || FAILED=1

at 40
for pair in "inside-0 outside-0" "inside-1 outside-0" "outside-0 inside-0" "outside-0 inside-1"; do
  expect cut $pair cut
done
expect cut inside-0 inside-1 open

at 70
expect bridge "$OPEN" outside-0 open
expect bridge outside-0 "$OPEN" open
expect bridge "$CLOSED" outside-0 cut
expect bridge outside-0 "$CLOSED" cut
expect bridge "$OPEN" "$CLOSED" open

at 100
for pair in "inside-0 outside-0" "inside-1 outside-0" "outside-0 inside-0" "outside-0 inside-1"; do
  expect healed $pair open
done

for _ in $(seq 1 40); do [ -s "$OUT/acks.json" ] && break; sleep 1; done
docker run --rm -v "$OUT:/out:ro" --entrypoint python "$IMAGE" -c '
import json, sys
acks = json.load(open("/out/acks.json"))
phase = [a for a in acks if a["kind"] == "phase"]
late = [a["applied_ms"] - a["planned_ms"] for a in phase]
bad = [a for a in acks if a["rc"] != 0]
ok = len(phase) == 12 and not bad and 0 <= min(late) and max(late) <= 500
print(("ok  " if ok else "FAIL"), f" shapers  {len(phase)}/12 phase acknowledgements, {len(bad)} failed, lateness {min(late)}..{max(late)} ms")
sys.exit(0 if ok else 1)
' || FAILED=1

# The counters are the kernel own account: a border that was cut must show drops.
drops="$(docker exec "$P-$CLOSED" tc -s qdisc show dev eth0 | awk '/netem 30:/ {getline; print}' | sed -E 's/.*dropped ([0-9]+).*/\1/')"
if [ "${drops:-0}" -gt 0 ]; then echo "ok    kernel   $CLOSED dropped $drops border packets on egress"
else echo "FAIL  kernel   $CLOSED shows no dropped border packets"; FAILED=1; fi

[ "$FAILED" -eq 0 ] && echo "PASS" || { echo "FAILED"; exit 1; }
