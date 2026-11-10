#!/usr/bin/env bash
# Link shaper sidecar. Shares the node's network namespace and holds NET_ADMIN.
#
# It is deliberately dumb: it fetches `tc` argument lists from the controller and runs them
# at the wall-clock times it is given. All decisions live in plan.py, where they are tested.
# Every pod receives the whole timeline before it starts, so a phase change does not depend
# on a control message arriving on time: the cut lands when the clock says so.
set -u
set -f # tc arguments are word-split on purpose; never glob them

C="${CAH_CONTROLLER:-http://controller:8080}"
POD="${POD_NAME:?POD_NAME is required}"
DEV="${CAH_DEV:-eth0}"

now_ms() { date +%s%3N; }
log() { echo "$(date -u +%FT%T.%3NZ) shaper $*"; }

ack() { # kind phase planned_ms applied_ms rc
  local i
  for i in 1 2 3 4 5; do
    curl -fsS -m 5 -o /dev/null -X POST \
      "$C/v1/ack?pod=$POD&kind=$1&phase=$2&planned_ms=$3&applied_ms=$4&rc=$5" && return 0
    sleep 1
  done
  log "ack lost kind=$1 phase=$2"
}

sleep_until_ms() {
  local delta=$(($1 - $(now_ms)))
  if [ "$delta" -gt 0 ]; then
    sleep "$(printf '%d.%03d' $((delta / 1000)) $((delta % 1000)))"
  fi
}

flush_phase() { # ack the phase whose commands just ran
  [ -n "$cur_phase" ] || return 0
  local applied
  applied="$(now_ms)"
  log "phase=$cur_phase planned_ms=$cur_at applied_ms=$applied late_ms=$((applied - cur_at)) rc=$cur_rc"
  ack phase "$cur_phase" "$cur_at" "$applied" "$cur_rc"
}

trap 'log "terminated"; exit 0' TERM INT

# 1. Build the qdisc tree with every border healthy.
until setup="$(curl -fsS -m 5 "$C/v1/setup/$POD")" && [ -n "$setup" ]; do sleep 1; done
rc=0
while IFS= read -r line; do
  [ -n "$line" ] || continue
  # shellcheck disable=SC2086
  tc $line || { rc=1; log "setup failed: tc $line"; }
done <<<"$setup"
log "setup rc=$rc"
ack setup setup 0 "$(now_ms)" "$rc"

# 2. Wait for the timeline. The controller publishes it once every node is meshed.
until plan="$(curl -fsS -m 5 "$C/v1/plan/$POD")" && [ -n "$plan" ]; do sleep 1; done
log "plan received lines=$(wc -l <<<"$plan")"

# 3. Run it. Lines are `epoch_ms|phase|tolerate|tc args`, sorted by time; a line with empty
#    args marks a phase this pod has nothing to change in, and is still acknowledged.
cur_phase="" cur_at=0 cur_rc=0
while IFS='|' read -r at phase tolerate args; do
  [ -n "$at" ] || continue
  if [ "$phase" != "$cur_phase" ]; then
    flush_phase
    cur_phase="$phase" cur_at="$at" cur_rc=0
    sleep_until_ms "$at"
  fi
  if [ -n "$args" ]; then
    # shellcheck disable=SC2086
    tc $args || { [ "$tolerate" = "1" ] || cur_rc=1; log "failed: tc $args"; }
  fi
done <<<"$plan"
flush_phase

log "timeline done"
# Counters are evidence: a border that was really cut shows dropped packets here.
tc -s qdisc show dev "$DEV"
tc -s filter show dev "$DEV" parent ffff:
sleep infinity &
wait $!
