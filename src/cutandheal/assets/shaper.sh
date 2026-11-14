#!/usr/bin/env bash
# Link shaper sidecar. Shares the node's network namespace and holds NET_ADMIN.
#
# It is deliberately dumb: it fetches `tc` argument lists from the controller and runs them
# at the wall-clock times it is given. All decisions live in plan.py, where they are tested.
# Every pod receives the whole timeline before it starts, so a phase change does not depend
# on a control message arriving on time: the cut lands when the clock says so.
#
# Hundreds of these wake at the same instant on the same machine. Anything a shaper forks at
# that instant competes with every other shaper, so the wake-up path forks exactly once (one
# `tc -batch` for the whole phase) or not at all. It sleeps on a bash builtin timer, reads
# the clock from a bash builtin, and sends its acknowledgement a random moment later. An
# earlier version called `sleep`, `date`, one `tc` per command and `curl` on waking; at 150
# pods on 4 CPUs the last pods applied a phase up to 2 s late.
set -u
export LC_ALL=C # EPOCHREALTIME must use a dot

C="${CAH_CONTROLLER:-http://controller:8080}"
POD="${POD_NAME:?POD_NAME is required}"
DEV="${CAH_DEV:-eth0}"

now() { NOW_MS=$((${EPOCHREALTIME/./} / 1000)); } # no fork

# A timer with no process behind it: read from a descriptor that never has data.
exec {IDLE}<> <(:)
nap_ms() { # milliseconds
  local t
  printf -v t '%d.%03d' $(($1 / 1000)) $(($1 % 1000))
  read -r -t "$t" -u "$IDLE" || true
}
log() { printf '%(%Y-%m-%dT%H:%M:%S)TZ shaper %s\n' -1 "$*"; }

ack() { # kind phase planned_ms applied_ms rc
  local i
  for i in 1 2 3 4 5; do
    curl -fsS -m 5 -o /dev/null -X POST \
      "$C/v1/ack?pod=$POD&kind=$1&phase=$2&planned_ms=$3&applied_ms=$4&rc=$5" && return 0
    sleep 1
  done
  log "ack lost kind=$1 phase=$2"
}

trap 'log "terminated"; exit 0' TERM INT

# 1. Build the qdisc tree with every border healthy.
until setup="$(curl -fsS -m 5 "$C/v1/setup/$POD")" && [ -n "$setup" ]; do sleep 1; done
rc=0
tc -batch - <<<"$setup" || rc=1
now
log "setup rc=$rc"
ack setup setup 0 "$NOW_MS" "$rc"

# The TCP timers this pod really has, read from its own network namespace, so a report can
# state the value that governed a run instead of assuming the documented default.
for key in tcp_retries2 tcp_keepalive_time; do
  val=unreadable
  { read -r val <"/proc/sys/net/ipv4/$key"; } 2>/dev/null || true
  log "kernel $key=$val"
done

# 2. Wait for the timeline. The controller publishes it once every node is meshed.
until plan="$(curl -fsS -m 5 "$C/v1/plan/$POD")" && [ -n "$plan" ]; do sleep 1; done

# 3. Parse it now, so nothing is left to do at a deadline but act. Lines are
#    `epoch_ms|phase|tc args`, sorted by time. A line with empty args marks a phase in which
#    this pod changes nothing; it is still acknowledged.
phases=() times=() batches=()
while IFS='|' read -r at phase args; do
  [ -n "$at" ] || continue
  last=$((${#phases[@]} - 1))
  if [ "$last" -lt 0 ] || [ "${phases[$last]}" != "$phase" ]; then
    phases+=("$phase") times+=("$at") batches+=("")
    last=$((last + 1))
  fi
  [ -z "$args" ] || batches[last]+="$args"$'\n'
done <<<"$plan"
log "plan received phases=${#phases[@]}"

# 4. Run it.
for i in "${!phases[@]}"; do
  now
  delta=$((times[i] - NOW_MS))
  [ "$delta" -le 0 ] || nap_ms "$delta"
  rc=0
  if [ -n "${batches[$i]}" ]; then
    tc -batch - <<<"${batches[$i]}" || rc=1
  fi
  now
  applied=$NOW_MS
  log "phase=${phases[$i]} planned_ms=${times[$i]} applied_ms=$applied late_ms=$((applied - times[i])) rc=$rc"
  # Acknowledge off the critical path: a random moment later, so the acknowledgements of
  # one phase are spread over three seconds instead of landing together.
  nap_ms $((RANDOM % 2700 + 300))
  ack phase "${phases[$i]}" "${times[$i]}" "$applied" "$rc"
done

log "timeline done"
# Counters are evidence: a border that was really cut shows dropped packets here.
tc -s qdisc show dev "$DEV"
tc -s filter show dev "$DEV" parent ffff:
sleep infinity &
wait $!
