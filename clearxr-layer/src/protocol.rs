//! Packet formats from `controller-bridge/protocol/PROTOCOL.md`: the controller packet the layer
//! decodes and the haptic packet it encodes. Version 2 only.

pub const CONTROLLER_MAGIC: u16 = 0x5343;
pub const HAPTIC_MAGIC: u16 = 0x4856;
pub const VERSION: u8 = 2;
pub const CONTROLLER_SIZE: usize = 248;
pub const HAPTIC_SIZE: usize = 24;

pub const FLAG_HEAD_RELATIVE: u16 = 1 << 0;
const FLAGS_DEFINED: u16 = 0x0001;
const ACTIVE_HANDS_DEFINED: u8 = 0x03;

#[allow(dead_code)]
pub mod buttons {
    pub const BUTTON_A: u16 = 1 << 0;
    pub const BUTTON_B: u16 = 1 << 1;
    pub const TRIGGER: u16 = 1 << 2;
    pub const GRIP: u16 = 1 << 3;
    pub const THUMBSTICK_CLICK: u16 = 1 << 4;
    pub const MENU: u16 = 1 << 5;
    pub const TOUCH_BUTTON_A: u16 = 1 << 6;
    pub const TOUCH_BUTTON_B: u16 = 1 << 7;
    pub const TOUCH_TRIGGER: u16 = 1 << 8;
    pub const TOUCH_GRIP: u16 = 1 << 9;
    pub const TOUCH_THUMBSTICK: u16 = 1 << 10;
    pub(super) const DEFINED: u16 = 0x07FF;
}

/// Bits 0–3 equal `XrSpaceLocationFlags`.
#[allow(dead_code)]
pub mod tracking {
    pub const ORIENTATION_VALID: u16 = 1 << 0;
    pub const POSITION_VALID: u16 = 1 << 1;
    pub const ORIENTATION_TRACKED: u16 = 1 << 2;
    pub const POSITION_TRACKED: u16 = 1 << 3;
    pub const LINEAR_VELOCITY_VALID: u16 = 1 << 4;
    pub const ANGULAR_VELOCITY_VALID: u16 = 1 << 5;
    pub const LOW_ACCURACY: u16 = 1 << 6;
    pub(super) const DEFINED: u16 = 0x007F;
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Pose {
    pub position: [f32; 3],
    /// x, y, z, w
    pub orientation: [f32; 4],
}

impl Default for Pose {
    fn default() -> Self {
        Pose { position: [0.0; 3], orientation: [0.0, 0.0, 0.0, 1.0] }
    }
}

/// One hand's block. Poses and velocities are in the head frame.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct HandBlock {
    pub sample_time_ns: u64,
    pub buttons: u16,
    pub tracking_flags: u16,
    pub thumbstick: [f32; 2],
    pub trigger: f32,
    pub grip: f32,
    pub grip_pose: Pose,
    pub aim_pose: Pose,
    pub linear_velocity: [f32; 3],
    pub angular_velocity: [f32; 3],
}

impl HandBlock {
    /// Tracking flags with the location bits cleared when any pose or velocity field is not
    /// finite, which the receiving rules treat as no valid pose.
    pub fn usable_tracking_flags(&self) -> u16 {
        let fields = self.grip_pose.position.iter()
            .chain(&self.grip_pose.orientation)
            .chain(&self.aim_pose.position)
            .chain(&self.aim_pose.orientation)
            .chain(&self.linear_velocity)
            .chain(&self.angular_velocity);
        let mut finite = true;
        for value in fields {
            finite &= value.is_finite();
        }
        if finite { self.tracking_flags } else { 0 }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ControllerPacket {
    pub active_hands: u8,
    pub flags: u16,
    pub sequence: u32,
    pub send_time_ns: u64,
    /// Left, then right.
    pub hands: [HandBlock; 2],
}

impl ControllerPacket {
    pub fn is_active(&self, hand: usize) -> bool {
        self.active_hands & (1 << hand) != 0
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Reject {
    TooShort,
    NotController,
    UnknownVersion,
}

pub fn decode_controller(bytes: &[u8]) -> Result<ControllerPacket, Reject> {
    if bytes.len() < 4 {
        return Err(Reject::TooShort);
    }
    let r = Reader(bytes);
    if r.u16(0) != CONTROLLER_MAGIC {
        return Err(Reject::NotController);
    }
    if r.u8(2) != VERSION {
        return Err(Reject::UnknownVersion);
    }
    if bytes.len() < CONTROLLER_SIZE {
        return Err(Reject::TooShort);
    }
    let hand = |base: usize| HandBlock {
        sample_time_ns: r.u64(base),
        buttons: r.u16(base + 8) & buttons::DEFINED,
        tracking_flags: r.u16(base + 10) & tracking::DEFINED,
        thumbstick: [r.f32(base + 16), r.f32(base + 20)],
        trigger: r.f32(base + 24),
        grip: r.f32(base + 28),
        grip_pose: r.pose(base + 32),
        aim_pose: r.pose(base + 60),
        linear_velocity: r.vec3(base + 88),
        angular_velocity: r.vec3(base + 100),
    };
    Ok(ControllerPacket {
        active_hands: r.u8(3) & ACTIVE_HANDS_DEFINED,
        flags: r.u16(4) & FLAGS_DEFINED,
        sequence: r.u32(8),
        send_time_ns: r.u64(16),
        hands: [hand(24), hand(136)],
    })
}

/// Whether `sequence` is newer than `last`, with wrapping arithmetic.
pub fn is_newer(sequence: u32, last: u32) -> bool {
    (sequence.wrapping_sub(last) as i32) > 0
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum HapticCommand {
    Apply { duration_ns: u64, frequency: f32, amplitude: f32 },
    Stop,
}

/// `hand` is 0 for left, 1 for right.
pub fn encode_haptic(hand: u8, command: HapticCommand) -> [u8; HAPTIC_SIZE] {
    let (code, duration_ns, frequency, amplitude) = match command {
        HapticCommand::Apply { duration_ns, frequency, amplitude } => (0u8, duration_ns, frequency, amplitude),
        HapticCommand::Stop => (1u8, 0, 0.0, 0.0),
    };
    let mut bytes = [0u8; HAPTIC_SIZE];
    bytes[0..2].copy_from_slice(&HAPTIC_MAGIC.to_le_bytes());
    bytes[2] = VERSION;
    bytes[3] = hand;
    bytes[4] = code;
    bytes[8..16].copy_from_slice(&duration_ns.to_le_bytes());
    bytes[16..20].copy_from_slice(&frequency.to_le_bytes());
    bytes[20..24].copy_from_slice(&amplitude.to_le_bytes());
    bytes
}

struct Reader<'a>(&'a [u8]);

impl Reader<'_> {
    fn array<const N: usize>(&self, offset: usize) -> [u8; N] {
        self.0[offset..offset + N].try_into().unwrap()
    }
    fn u8(&self, offset: usize) -> u8 {
        self.0[offset]
    }
    fn u16(&self, offset: usize) -> u16 {
        u16::from_le_bytes(self.array(offset))
    }
    fn u32(&self, offset: usize) -> u32 {
        u32::from_le_bytes(self.array(offset))
    }
    fn u64(&self, offset: usize) -> u64 {
        u64::from_le_bytes(self.array(offset))
    }
    fn f32(&self, offset: usize) -> f32 {
        f32::from_le_bytes(self.array(offset))
    }
    fn vec3(&self, offset: usize) -> [f32; 3] {
        [self.f32(offset), self.f32(offset + 4), self.f32(offset + 8)]
    }
    fn pose(&self, offset: usize) -> Pose {
        Pose {
            position: self.vec3(offset),
            orientation: [self.f32(offset + 12), self.f32(offset + 16), self.f32(offset + 20), self.f32(offset + 24)],
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    fn vectors() -> Vec<Value> {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/protocol/vectors.json");
        let file: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        file["vectors"].as_array().unwrap().clone()
    }

    fn bytes(vector: &Value) -> Vec<u8> {
        let hex = vector["hex"].as_str().unwrap();
        (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap()).collect()
    }

    fn floats<const N: usize>(value: &Value) -> [f32; N] {
        let array = value.as_array().unwrap();
        std::array::from_fn(|i| array[i].as_f64().unwrap() as f32)
    }

    fn pose(value: &Value) -> Pose {
        Pose { position: floats(&value["position"]), orientation: floats(&value["orientation"]) }
    }

    fn hand(value: &Value) -> HandBlock {
        HandBlock {
            sample_time_ns: value["sampleTimeNs"].as_u64().unwrap(),
            buttons: value["buttons"].as_u64().unwrap() as u16,
            tracking_flags: value["trackingFlags"].as_u64().unwrap() as u16,
            thumbstick: floats(&value["thumbstick"]),
            trigger: value["trigger"].as_f64().unwrap() as f32,
            grip: value["grip"].as_f64().unwrap() as f32,
            grip_pose: pose(&value["gripPose"]),
            aim_pose: pose(&value["aimPose"]),
            linear_velocity: floats(&value["linearVelocity"]),
            angular_velocity: floats(&value["angularVelocity"]),
        }
    }

    #[test]
    fn controller_vectors() {
        let mut checked = 0;
        for vector in vectors().iter().filter(|v| v["type"] == "controller") {
            let name = vector["name"].as_str().unwrap();
            let decoded = decode_controller(&bytes(vector));
            if vector.get("reject").is_some() {
                assert!(decoded.is_err(), "{name}: accepted a malformed packet");
            } else {
                let fields = &vector["fields"];
                let expected = ControllerPacket {
                    active_hands: fields["activeHands"].as_u64().unwrap() as u8,
                    flags: fields["flags"].as_u64().unwrap() as u16,
                    sequence: fields["sequence"].as_u64().unwrap() as u32,
                    send_time_ns: fields["sendTimeNs"].as_u64().unwrap(),
                    hands: [hand(&fields["left"]), hand(&fields["right"])],
                };
                assert_eq!(decoded, Ok(expected), "{name}");
            }
            checked += 1;
        }
        assert!(checked >= 10);
    }

    #[test]
    fn haptic_vectors() {
        let mut checked = 0;
        for vector in vectors().iter().filter(|v| v["type"] == "haptic" && v.get("fields").is_some()) {
            if vector.get("decodeOnly").is_some() {
                continue;
            }
            let fields = &vector["fields"];
            let command = match fields["command"].as_u64().unwrap() {
                0 => HapticCommand::Apply {
                    duration_ns: fields["durationNs"].as_u64().unwrap(),
                    frequency: fields["frequency"].as_f64().unwrap() as f32,
                    amplitude: fields["amplitude"].as_f64().unwrap() as f32,
                },
                _ => HapticCommand::Stop,
            };
            let encoded = encode_haptic(fields["hand"].as_u64().unwrap() as u8, command);
            assert_eq!(encoded.to_vec(), bytes(vector), "{}", vector["name"]);
            checked += 1;
        }
        assert_eq!(checked, 3);
    }

    #[test]
    fn sequence_wraps() {
        assert!(is_newer(0, u32::MAX));
        assert!(is_newer(5, 4));
        assert!(!is_newer(4, 4));
        assert!(!is_newer(u32::MAX, 0));
    }

    #[test]
    fn non_finite_pose_has_no_location() {
        let mut hand = HandBlock { tracking_flags: 0x3F, ..Default::default() };
        assert_eq!(hand.usable_tracking_flags(), 0x3F);
        hand.angular_velocity[1] = f32::NAN;
        assert_eq!(hand.usable_tracking_flags(), 0);
    }
}
