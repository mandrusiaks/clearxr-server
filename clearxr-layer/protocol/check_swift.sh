#!/bin/sh
# Compiles the visionOS client's packet code for the Mac and checks it against vectors.json.
#   check_swift.sh <path to the client's ClearXR/Models/ControllerBridgePacket.swift>
set -eu
here=$(cd "$(dirname "$0")" && pwd)
packet=${1:?usage: check_swift.sh <path to ControllerBridgePacket.swift>}
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
xcrun swiftc -O -o "$out/check" "$packet" "$here/swift/main.swift"
"$out/check" "$here/vectors.json"
