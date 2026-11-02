#!/usr/bin/env bash
# Run './dev.sh build MODULE...' detached (survives the agent session's process cleanup).
# Writes logs/dev-build-bg.log and state/dev-build-bg.pid; 'tools/dev-build-bg.sh wait'
# blocks until it finishes and prints the result.
G="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
LOG="$G/logs/dev-build-bg.log" PID="$G/state/dev-build-bg.pid"
if [[ ${1:-} == wait ]]; then
    while [[ -f $PID ]] && kill -0 "$(cat "$PID")" 2>/dev/null; do sleep 10; done
    tail -c 4000 "$LOG" | tr '\r' '\n' | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' | grep -v '^$' \
        | grep -vE 'memory stall|^\[ *[0-9]+% ' | tail -"${2:-15}" | cut -c1-240
    exit 0
fi
# The child writes its own pid: setsid forks when it isn't a group leader, so $! would be the wrong one
rm -f "$PID"
cd "$G" && setsid nohup bash -c 'echo $$ > "$0"; exec ./dev.sh build "$@"' "$PID" "$@" > "$LOG" 2>&1 < /dev/null &
for _ in 1 2 3 4 5 6 7 8 9 10; do [[ -s $PID ]] && break; sleep 0.5; done
echo "started build of $* (pid $(cat "$PID"), log $LOG)"
