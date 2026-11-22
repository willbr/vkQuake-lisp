#!/bin/sh
# Validate before passing generated code to the original, trusting interpreter.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ "$#" -lt 2 ]; then
    echo "usage: $0 PROGS.DAT FUNCTION [FLOAT ...]" >&2
    exit 2
fi
python3 "$root/tools/quakec/check-stock.py" "$1"
exec "$root/build/quakec/bin/stock-vm" "$@"
