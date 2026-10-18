#!/bin/sh
here=$(cd "$(dirname "$0")" && pwd)
py=${PYTHON:-python3}
out=$(mktemp -d)
"$py" "$here/pyapi.py" "$1" > "$out/py.json" 2> "$out/py.err" || { tail -8 "$out/py.err"; exit 2; }
node --no-warnings --import "$here/loader.mjs" "$here/jsapi.mjs" "$1" > "$out/js.json" 2> "$out/js.err" || { tail -8 "$out/js.err"; exit 2; }
node "$here/compare_api.mjs" "$out/py.json" "$out/js.json"
