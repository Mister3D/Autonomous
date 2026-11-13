//! Same framing as `autonomous/services/companion_proto.py`.

pub const OPEN: u8 = 1;
pub const OPEN_OK: u8 = 2;
pub const OPEN_ERR: u8 = 3;
pub const DATA: u8 = 4;
pub const CLOSE: u8 = 5;
pub const DNS: u8 = 6;
pub const DNS_OK: u8 = 7;
pub const DNS_ERR: u8 = 8;
pub const MCP_CALL: u8 = 9;
pub const MCP_RESULT: u8 = 10;
pub const PING: u8 = 11;
pub const PONG: u8 = 12;
pub const NOTIFY: u8 = 13;

/// One frame. Large enough for a desktop screenshot (base64) plus its text.
pub const MAX_PAYLOAD: usize = 8 * 1024 * 1024;

pub fn encode(op: u8, stream_id: u32, payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(9 + payload.len());
    out.push(op);
    out.extend_from_slice(&stream_id.to_be_bytes());
    out.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    out.extend_from_slice(payload);
    out
}

pub fn decode(data: &[u8]) -> Option<(u8, u32, &[u8])> {
    if data.len() < 9 {
        return None;
    }
    let op = data[0];
    let stream_id = u32::from_be_bytes(data[1..5].try_into().ok()?);
    let len = u32::from_be_bytes(data[5..9].try_into().ok()?) as usize;
    if data.len() != 9 + len || len > MAX_PAYLOAD {
        return None;
    }
    Some((op, stream_id, &data[9..]))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip() {
        let raw = encode(OPEN, 7, b"example.com\n443");
        let (op, id, payload) = decode(&raw).unwrap();
        assert_eq!(op, OPEN);
        assert_eq!(id, 7);
        assert_eq!(payload, b"example.com\n443");
    }
}
