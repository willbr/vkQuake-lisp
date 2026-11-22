#!/bin/sh
# Fetch reference sources and build the stock NetQuake compiler/test toolchain.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
out="$root/build/quakec"

fetch_reference() {
    url=$1
    revision=$2
    destination=$3
    if [ ! -d "$destination/.git" ]; then
        if [ -e "$destination" ]; then
            echo "Refusing to replace existing directory: $destination" >&2
            exit 1
        fi
        git init -q "$destination"
        git -C "$destination" remote add origin "$url"
        git -C "$destination" fetch --depth 1 origin "$revision"
        git -C "$destination" checkout -q --detach FETCH_HEAD
    fi
    if [ "$(git -C "$destination" rev-parse HEAD)" != "$revision" ]; then
        echo "Expected $destination at $revision; leaving checkout untouched." >&2
        exit 1
    fi
    if ! git -C "$destination" diff --quiet HEAD --; then
        echo "Reference has local changes: $destination; leaving it untouched." >&2
        exit 1
    fi
}

mkdir -p "$root/third_party" "$out/bin" "$out/fteqcc-src" "$out/reference/progs"
fetch_reference https://github.com/id-Software/Quake-Tools.git \
    c0d1b91c74eb654365ac7755bc837e497caaca73 "$root/third_party/quake-tools"
fetch_reference https://github.com/fte-team/fteqw.git \
    f09ac7cccd2d713ddf881d3f1324703082c2cfe4 "$root/third_party/fteqw"
fetch_reference https://github.com/id-Software/Quake.git \
    bf4ac424ce754894ac8f1dae6a3981954bc9852d "$root/third_party/quake"

# Build copies so upstream checkouts remain clean and usable as references.
cp -R "$root/third_party/fteqw/engine/qclib/." "$out/fteqcc-src/"
if ! make -C "$out/fteqcc-src" qcc CC="${CC:-cc}" CFLAGS="${CFLAGS:--O2}" DEBUG=1 \
    >"$out/build.log" 2>&1; then
    cat "$out/build.log" >&2
    exit 1
fi
cp "$out/fteqcc-src/fteqcc.bin" "$out/bin/fteqcc"

# Compile the original interpreter unchanged, with a minimal command-line host.
# Copying it here lets its quoted quakedef.h include resolve to our host shim.
mkdir -p "$out/stock-vm"
cp "$root/third_party/quake/WinQuake/pr_exec.c" "$out/stock-vm/pr_exec.c"
cp "$root/third_party/quake/WinQuake/pr_comp.h" "$out/stock-vm/pr_comp.h"
cp "$root/third_party/quake/WinQuake/progdefs.q1" "$out/stock-vm/progdefs.q1"
cp "$root/tools/quakec/stock-vm/quakedef.h" "$out/stock-vm/quakedef.h"
"${CC:-cc}" -std=c11 -O2 -fno-strict-aliasing -Wno-pointer-to-int-cast \
    -I"$out/stock-vm" "$out/stock-vm/pr_exec.c" \
    "$root/tools/quakec/stock-vm/main.c" -o "$out/bin/stock-vm"
cp -R "$root/third_party/quake-tools/qcc/v101qc/." "$out/reference/progs/"
cd "$out/reference/progs"
if ! "$out/bin/fteqcc" -Tq1 -O0 -Fwasm >"$out/compile.log" 2>&1; then
    cat "$out/compile.log" >&2
    exit 1
fi

python3 "$root/tools/quakec/check-stock.py" "$out/reference/progs.dat"
tail -n 3 "$out/compile.log"
printf '\nCompiler: %s\nAssembly listing: %s\n' \
    "$out/bin/fteqcc" "$out/reference/progs/qc.asm"
printf 'Stock interpreter CLI: %s\n' "$out/bin/stock-vm"
