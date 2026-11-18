"""Binary frames shared by the instance and the Rust companion.

One WebSocket binary message = one frame:

    u8  op
    u32 stream id (big endian)
    u32 payload length
    bytes payload
"""

from __future__ import annotations

import struct

OP_OPEN = 1
OP_OPEN_OK = 2
OP_OPEN_ERR = 3
OP_DATA = 4
OP_CLOSE = 5
OP_DNS = 6
OP_DNS_OK = 7
OP_DNS_ERR = 8
OP_MCP_CALL = 9
OP_MCP_RESULT = 10
OP_PING = 11
OP_PONG = 12
OP_NOTIFY = 13

_HEADER = struct.Struct("!BII")
# One frame. Room for a large companion image (base64) plus its text.
MAX_PAYLOAD = 160 * 1024 * 1024


def encode_frame(op: int, stream_id: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("frame too large")
    return _HEADER.pack(op & 0xFF, stream_id & 0xFFFFFFFF, len(payload)) + payload


def decode_frame(data: bytes) -> tuple[int, int, bytes]:
    if len(data) < _HEADER.size:
        raise ValueError("short frame")
    op, stream_id, length = _HEADER.unpack_from(data)
    if length > MAX_PAYLOAD or length != len(data) - _HEADER.size:
        raise ValueError("bad frame length")
    return op, stream_id, data[_HEADER.size :]
