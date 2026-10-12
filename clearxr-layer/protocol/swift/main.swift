// Checks the client's ControllerBridgePacket.swift against vectors.json: the controller encoder
// against every accepted controller vector, and the haptic decoder against every haptic vector.
// Run it through ../check_swift.sh.

import Foundation
import simd

struct VectorFile: Decodable {
    let vectors: [Vector]
}

struct Vector: Decodable {
    let name: String
    let type: String
    let hex: String
    let fields: Fields?
    let reject: String?
    let decodeOnly: Bool?
}

struct Fields: Decodable {
    // Controller
    let activeHands: UInt8?
    let flags: UInt16?
    let sequence: UInt32?
    let sendTimeNs: UInt64?
    let left: HandFields?
    let right: HandFields?
    // Haptic
    let hand: UInt8?
    let command: UInt8?
    let durationNs: UInt64?
    let frequency: Float?
    let amplitude: Float?
}

struct HandFields: Decodable {
    let sampleTimeNs: UInt64
    let buttons: UInt16
    let trackingFlags: UInt16
    let thumbstick: [Float]
    let trigger: Float
    let grip: Float
    let gripPose: PoseFields
    let aimPose: PoseFields
    let linearVelocity: [Float]
    let angularVelocity: [Float]

    var hand: ControllerBridgeHand {
        ControllerBridgeHand(
            sampleTimeNs: sampleTimeNs,
            buttons: .init(rawValue: buttons),
            trackingFlags: .init(rawValue: trackingFlags),
            thumbstick: SIMD2(thumbstick[0], thumbstick[1]),
            trigger: trigger,
            grip: grip,
            gripPose: gripPose.pose,
            aimPose: aimPose.pose,
            linearVelocity: SIMD3(linearVelocity[0], linearVelocity[1], linearVelocity[2]),
            angularVelocity: SIMD3(angularVelocity[0], angularVelocity[1], angularVelocity[2]))
    }
}

struct PoseFields: Decodable {
    let position: [Float]
    let orientation: [Float]

    var pose: ControllerBridgePose {
        ControllerBridgePose(
            position: SIMD3(position[0], position[1], position[2]),
            orientation: simd_quatf(vector: SIMD4(orientation[0], orientation[1], orientation[2], orientation[3])))
    }
}

func bytes(_ hex: String) -> Data {
    var data = Data()
    var index = hex.startIndex
    while index < hex.endIndex {
        let next = hex.index(index, offsetBy: 2)
        data.append(UInt8(hex[index..<next], radix: 16)!)
        index = next
    }
    return data
}

func hex(_ data: Data) -> String {
    data.map { String(format: "%02x", $0) }.joined()
}

/// Returns a failure description, or nil when the vector passes.
func check(_ vector: Vector) -> String? {
    switch (vector.type, vector.fields) {
    case ("controller", let fields?):
        // The client encodes controller packets but never decodes them.
        guard vector.decodeOnly != true else { return nil }
        guard fields.flags == ControllerBridgePacket.headRelative else {
            return "encoder always sets HEAD_RELATIVE; vector has flags \(fields.flags ?? 0)"
        }
        let active = fields.activeHands ?? 0
        let packet = ControllerBridgePacket(
            sequence: fields.sequence!,
            sendTimeNs: fields.sendTimeNs!,
            left: active & 1 != 0 ? fields.left!.hand : nil,
            right: active & 2 != 0 ? fields.right!.hand : nil)
        let encoded = hex(packet.encoded())
        return encoded == vector.hex ? nil : "encoded \(encoded)"
    case ("controller", nil):
        return nil
    case ("haptic", let fields?):
        guard let decoded = ControllerBridgeHaptic(bytes(vector.hex)) else { return "rejected" }
        let expected = (fields.hand!, fields.command!, fields.durationNs!, fields.frequency!, fields.amplitude!)
        let actual = (decoded.hand.rawValue, decoded.command.rawValue, decoded.durationNs, decoded.frequency, decoded.amplitude)
        return expected == actual ? nil : "decoded \(actual), expected \(expected)"
    case ("haptic", nil):
        return ControllerBridgeHaptic(bytes(vector.hex)) == nil ? nil : "accepted a malformed packet"
    default:
        return "unknown vector type \(vector.type)"
    }
}

let path = CommandLine.arguments.dropFirst().first ?? "vectors.json"
let file = try JSONDecoder().decode(VectorFile.self, from: Data(contentsOf: URL(fileURLWithPath: path)))
var failures = 0
for vector in file.vectors {
    if let failure = check(vector) {
        failures += 1
        print("FAIL \(vector.name): \(failure)")
    }
}
print("\(file.vectors.count - failures)/\(file.vectors.count) vectors pass")
exit(failures == 0 ? 0 : 1)
