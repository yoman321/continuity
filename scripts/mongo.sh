#!/usr/bin/env bash
# The ledger's database. There is no file store and no fallback (`AGENTS.md` §2), so a run
# needs this up.
#
#   ./scripts/mongo.sh start | stop | status
#
# The port is the source of truth, never the process table. `pkill` returns before mongod has
# finished shutting down, so a `stop` immediately followed by a `status` or a `start` saw a
# dying process and reported it as alive — which made `start` skip the launch and leave nothing
# listening. Both verbs now wait for the socket to actually change state.
set -euo pipefail
cd "$(dirname "$0")/.."
DBPATH=${MONGO_DBPATH:-data/mongo}
PORT=${MONGO_PORT:-27017}

listening() { nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1; }

wait_for() {   # wait_for up|down, up to ~10s
  for _ in $(seq 1 40); do
    if [ "$1" = up ]; then listening && return 0; else listening || return 0; fi
    sleep 0.25
  done
  return 1
}

case "${1:-status}" in
  start)
    if listening; then echo "already running on $PORT"; exit 0; fi
    mkdir -p "$DBPATH"
    # Not --fork: macOS rejects it ("Server fork+exec ... is incompatible with macOS").
    # nohup plus & detaches the same way and works on both platforms.
    nohup mongod --dbpath "$DBPATH" --port "$PORT" --bind_ip 127.0.0.1 \
          >> "$DBPATH/mongod.log" 2>&1 &
    if wait_for up; then
      echo "mongod up on 127.0.0.1:$PORT  (dbpath $DBPATH)"
    else
      echo "mongod did not come up; see $DBPATH/mongod.log" >&2; exit 1
    fi ;;
  stop)
    if ! listening; then echo "not running"; exit 0; fi
    pkill -f "mongod --dbpath $DBPATH" || true
    if wait_for down; then echo "stopped"; else
      echo "mongod still listening on $PORT" >&2; exit 1
    fi ;;
  status)
    if listening; then echo "running on $PORT"; else echo "not running"; fi ;;
  *) echo "usage: $0 {start|stop|status}" >&2; exit 2 ;;
esac
