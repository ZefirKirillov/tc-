#!/bin/sh
# ./run.sh scenarios/x.json — run a scenario through both bots and diff.
set -e
here=$(cd "$(dirname "$0")" && pwd)
py=${PYTHON:-python3}
out=$(mktemp -d)
"$py" "$here/pyref.py" "$1" > "$out/py.json" 2> "$out/py.err" || { tail -5 "$out/py.err"; exit 2; }
node --no-warnings --import "$here/loader.mjs" "$here/jsref.mjs" "$1" > "$out/js.json" 2> "$out/js.err" || { cat "$out/js.err"; exit 2; }
[ -n "$VERBOSE" ] && grep -v "DeprecationWarning\|trace-deprecation\|ExperimentalWarning" "$out/js.err" | head -20
node "$here/compare.mjs" "$out/py.json" "$out/js.json"
