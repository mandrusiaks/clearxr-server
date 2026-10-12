#!/usr/bin/env python3
"""Writes vectors.json: golden byte vectors for the packets specified in PROTOCOL.md.

This is an independent third encoder. The Swift client and the Rust layer each check their own
encoders and decoders against its output. Run with --check to confirm vectors.json matches.
"""

import argparse
import json
import struct
import sys
from pathlib import Path

CONTROLLER_MAGIC = 0x5343
HAPTIC_MAGIC = 0x4856

V1_HEADER = struct.Struct("<HBB")
V1_HAND = struct.Struct("<HH11f")
V2_HEADER = struct.Struct("<HBBHHIIQ")
V2_HAND = struct.Struct("<QHHI24f")
HAPTIC_V1 = struct.Struct("<HBBQff")
HAPTIC_V2 = struct.Struct("<HBBBBHQff")

assert V1_HEADER.size + 2 * V1_HAND.size == 100
assert V2_HEADER.size == 24 and V2_HAND.size == 112
assert HAPTIC_V1.size == 20 and HAPTIC_V2.size == 24

IDENTITY = [0.0, 0.0, 0.0, 1.0]
EMPTY_V1_HAND = {
    "buttons": 0, "thumbstick": [0.0, 0.0], "trigger": 0.0, "grip": 0.0,
    "position": [0.0, 0.0, 0.0], "orientation": IDENTITY,
}
EMPTY_V2_HAND = {
    "sampleTimeNs": 0, "buttons": 0, "trackingFlags": 0,
    "thumbstick": [0.0, 0.0], "trigger": 0.0, "grip": 0.0,
    "gripPose": {"position": [0.0, 0.0, 0.0], "orientation": IDENTITY},
    "aimPose": {"position": [0.0, 0.0, 0.0], "orientation": IDENTITY},
    "linearVelocity": [0.0, 0.0, 0.0], "angularVelocity": [0.0, 0.0, 0.0],
}


def encode_v1_hand(h):
    return V1_HAND.pack(h["buttons"], 0, *h["thumbstick"], h["trigger"], h["grip"],
                        *h["position"], *h["orientation"])


def encode_controller_v1(p):
    return (V1_HEADER.pack(CONTROLLER_MAGIC, 1, p["activeHands"])
            + encode_v1_hand(p["left"]) + encode_v1_hand(p["right"]))


def encode_v2_hand(h):
    return V2_HAND.pack(
        h["sampleTimeNs"], h["buttons"], h["trackingFlags"], 0,
        *h["thumbstick"], h["trigger"], h["grip"],
        *h["gripPose"]["position"], *h["gripPose"]["orientation"],
        *h["aimPose"]["position"], *h["aimPose"]["orientation"],
        *h["linearVelocity"], *h["angularVelocity"],
    )


def encode_controller_v2(p):
    header = V2_HEADER.pack(CONTROLLER_MAGIC, 2, p["activeHands"], p["flags"], 0,
                            p["sequence"], 0, p["sendTimeNs"])
    return header + encode_v2_hand(p["left"]) + encode_v2_hand(p["right"])


def encode_haptic_v1(p):
    return HAPTIC_V1.pack(HAPTIC_MAGIC, 1, p["hand"], p["durationNs"], p["frequency"], p["amplitude"])


def encode_haptic_v2(p):
    return HAPTIC_V2.pack(HAPTIC_MAGIC, 2, p["hand"], p["command"], 0, 0,
                          p["durationNs"], p["frequency"], p["amplitude"])


def tracked_hand(sample_time_ns, buttons, flags, stick, trigger, grip, grip_pose, aim_pose, lin, ang):
    return {
        "sampleTimeNs": sample_time_ns, "buttons": buttons, "trackingFlags": flags,
        "thumbstick": stick, "trigger": trigger, "grip": grip,
        "gripPose": grip_pose, "aimPose": aim_pose,
        "linearVelocity": lin, "angularVelocity": ang,
    }


def accepted_cases():
    """Every float here is exactly representable in binary32, so comparisons can be exact."""
    v2_both = {
        "version": 2, "activeHands": 0b11, "flags": 0x0001, "sequence": 7,
        "sendTimeNs": 1_234_567_890_123,
        "left": tracked_hand(
            1_234_550_000_000, 0b000_0011_0101_0001, 0b0011_1111,
            [-0.25, 0.5], 0.0, 1.0,
            {"position": [-0.25, -0.375, -0.5], "orientation": [0.5, -0.5, 0.5, 0.5]},
            {"position": [-0.21875, -0.34375, -0.5625], "orientation": [0.5, -0.5, 0.5, 0.5]},
            [0.125, -0.0625, 0.0], [0.0, 1.5, -0.75],
        ),
        "right": tracked_hand(
            1_234_560_000_000, 0b111_1111_1111, 0b0011_1111,
            [1.0, -1.0], 0.75, 0.5,
            {"position": [0.25, -0.375, -0.5], "orientation": IDENTITY},
            {"position": [0.25, -0.34375, -0.5625], "orientation": [-0.5, 0.5, -0.5, 0.5]},
            [-0.5, 0.25, 2.25], [-3.0, 0.0, 0.125],
        ),
    }
    v2_partial = {
        "version": 2, "activeHands": 0b11, "flags": 0x0001, "sequence": 0xFFFF_FFFF,
        "sendTimeNs": 18_446_744_073_709_551_615,
        "left": tracked_hand(
            18_446_744_073_709_000_000, 0b100_0000_0000, 0b0111_1111,
            [0.0, 0.0], 0.0625, 0.0,
            {"position": [-0.125, -0.5, -0.25], "orientation": [0.0, 0.0, 1.0, 0.0]},
            {"position": [-0.125, -0.46875, -0.3125], "orientation": [0.0, 0.0, 1.0, 0.0]},
            [0.25, 0.0, -0.125], [0.5, -0.25, 0.0],
        ),
        # Connected but untracked: buttons still report, pose fields carry the last pose or zero.
        "right": dict(EMPTY_V2_HAND, sampleTimeNs=18_446_744_073_708_000_000, buttons=0b0000_0001),
    }
    v2_none = {
        "version": 2, "activeHands": 0, "flags": 0x0001, "sequence": 0, "sendTimeNs": 0,
        "left": EMPTY_V2_HAND, "right": EMPTY_V2_HAND,
    }
    return [
        ("controller-v2-both-hands-tracked", "controller", v2_both, encode_controller_v2),
        ("controller-v2-left-low-accuracy-right-untracked-limits", "controller", v2_partial, encode_controller_v2),
        ("controller-v2-no-active-hands", "controller", v2_none, encode_controller_v2),
        ("haptic-v2-apply-left", "haptic",
         {"version": 2, "hand": 0, "command": 0, "durationNs": 100_000_000, "frequency": 160.0, "amplitude": 0.75},
         encode_haptic_v2),
        ("haptic-v2-apply-right-shortest-unspecified-frequency", "haptic",
         {"version": 2, "hand": 1, "command": 0, "durationNs": 0, "frequency": 0.0, "amplitude": 1.0},
         encode_haptic_v2),
        ("haptic-v2-stop-right", "haptic",
         {"version": 2, "hand": 1, "command": 1, "durationNs": 0, "frequency": 0.0, "amplitude": 0.0},
         encode_haptic_v2),
    ]


def with_reserved_set(data, edits):
    """Returns data with every reserved field and bit set, to check receivers ignore them."""
    out = bytearray(data)
    for fmt, offset, value in edits:
        struct.pack_into(fmt, out, offset, value)
    return bytes(out)


def build():
    vectors = []
    encoded = {}
    for name, kind, fields, encode in accepted_cases():
        data = encode(fields)
        encoded[name] = data
        vectors.append({"name": name, "type": kind, "fields": fields, "hex": data.hex()})

    v2 = encoded["controller-v2-both-hands-tracked"]
    vectors.append({
        "name": "controller-v2-trailing-bytes-ignored", "type": "controller", "decodeOnly": True,
        "fields": next(v["fields"] for v in vectors if v["name"] == "controller-v2-both-hands-tracked"),
        "hex": (v2 + bytes(8)).hex(),
    })
    both = next(v["fields"] for v in vectors if v["name"] == "controller-v2-both-hands-tracked")
    left_buttons, right_buttons = both["left"]["buttons"], both["right"]["buttons"]
    left_flags, right_flags = both["left"]["trackingFlags"], both["right"]["trackingFlags"]
    vectors.append({
        "name": "controller-v2-reserved-bits-ignored", "type": "controller", "decodeOnly": True, "fields": both,
        "hex": with_reserved_set(v2, [
            ("<B", 3, 0xFF), ("<H", 4, 0xFFFF), ("<H", 6, 0xFFFF), ("<I", 12, 0xFFFF_FFFF),
            ("<H", 24 + 8, left_buttons | 0xF800), ("<H", 24 + 10, left_flags | 0xFF80), ("<I", 24 + 12, 0xFFFF_FFFF),
            ("<H", 136 + 8, right_buttons | 0xF800), ("<H", 136 + 10, right_flags | 0xFF80), ("<I", 136 + 12, 0xFFFF_FFFF),
        ]).hex(),
    })
    haptic = encoded["haptic-v2-apply-left"]
    vectors.append({
        "name": "haptic-v2-reserved-bits-ignored", "type": "haptic", "decodeOnly": True,
        "fields": next(v["fields"] for v in vectors if v["name"] == "haptic-v2-apply-left"),
        "hex": with_reserved_set(haptic, [("<B", 5, 0xFF), ("<H", 6, 0xFFFF)]).hex(),
    })

    v1_controller = encode_controller_v1({
        "activeHands": 0b11,
        "left": dict(EMPTY_V1_HAND, buttons=0b0000_0010_0101, thumbstick=[0.5, -0.25], trigger=0.75, grip=0.125),
        "right": EMPTY_V1_HAND,
    })
    v1_haptic = encode_haptic_v1({"hand": 1, "durationNs": 32_000_000, "frequency": 0.0, "amplitude": 0.5})
    rejects = [
        ("controller-wrong-magic", "controller", struct.pack("<H", 0x5344) + v2[2:], "magic is not 0x5343"),
        ("controller-unknown-version", "controller", v2[:2] + bytes([3]) + v2[3:], "version 3 is unknown"),
        ("controller-version-0", "controller", v2[:2] + bytes([0]) + v2[3:], "version 0 is unknown"),
        ("controller-v1-not-accepted", "controller", v1_controller, "version 1 is not implemented"),
        ("controller-v2-truncated", "controller", v2[:-1], "shorter than 248 bytes"),
        ("controller-empty", "controller", b"", "shorter than 4 bytes"),
        ("haptic-wrong-magic", "haptic", struct.pack("<H", 0x4857) + haptic[2:], "magic is not 0x4856"),
        ("haptic-unknown-version", "haptic", haptic[:2] + bytes([3]) + haptic[3:], "version 3 is unknown"),
        ("haptic-v1-not-accepted", "haptic", v1_haptic, "version 1 is not implemented"),
        ("haptic-v2-truncated", "haptic", haptic[:23], "shorter than 24 bytes"),
        ("haptic-empty", "haptic", b"", "shorter than 4 bytes"),
        ("haptic-three-bytes", "haptic", haptic[:3], "shorter than 4 bytes"),
        ("haptic-v2-unknown-command", "haptic",
         encode_haptic_v2({"hand": 0, "command": 2, "durationNs": 0, "frequency": 0.0, "amplitude": 0.0}),
         "command 2 is unknown"),
        ("haptic-v2-unknown-hand", "haptic",
         encode_haptic_v2({"hand": 2, "command": 0, "durationNs": 0, "frequency": 0.0, "amplitude": 0.5}),
         "hand 2 is unknown"),
    ]
    for name, kind, data, reason in rejects:
        vectors.append({"name": name, "type": kind, "reject": reason, "hex": data.hex()})

    return {
        "comment": "Generated by generate_vectors.py from the layouts in PROTOCOL.md. Do not edit by hand.",
        "vectors": vectors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if vectors.json is out of date")
    args = parser.parse_args()

    path = Path(__file__).with_name("vectors.json")
    text = json.dumps(build(), indent=2) + "\n"
    if args.check:
        if not path.exists() or path.read_text() != text:
            print(f"{path} is out of date; run generate_vectors.py", file=sys.stderr)
            return 1
        print(f"{path} is current")
        return 0
    path.write_text(text)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
