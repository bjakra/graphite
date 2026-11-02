#!/usr/bin/env bash
# Run a command (default: bash) inside the Graphite build container, with the
# project mounted at the same path and your uid, so files stay owned by you.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
IMAGE=localhost/graphite-build:latest
if ! podman image exists "$IMAGE" || [[ "$ROOT/tools/container/Containerfile" -nt "$ROOT/state/container.stamp" ]]; then
    podman build -t "$IMAGE" -f "$ROOT/tools/container/Containerfile" "$ROOT/tools/container"
    mkdir -p "$ROOT/state"; touch "$ROOT/state/container.stamp"
fi
(( $# )) || set -- bash
exec podman run --rm -it --userns=keep-id --privileged \
    -v "$ROOT:$ROOT" -w "$PWD" -e TERM -e NO_COLOR -e HOME="$ROOT/state/container-home" \
    --device /dev/kvm "$IMAGE" "$@"
