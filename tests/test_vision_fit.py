"""Images sent to the model are scaled down; the file on disk is not."""

from pathlib import Path

from autonomous.services.chat_attachments import MAX_BYTES, MAX_IMAGE_ATTACHMENTS
from autonomous.services.grounding_image import png_bytes
from autonomous.services.vision_fit import MAX_SIDE, fit_image_b64, fit_image_path


def test_pasted_image_caps():
    assert MAX_IMAGE_ATTACHMENTS == 16
    assert MAX_BYTES == 100 * 1024 * 1024


def _png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    import struct
    return struct.unpack(">II", data[16:24])


def test_wide_image_is_scaled_for_the_model(tmp_path: Path):
    raw = png_bytes(4000, 30, bytes([10, 20, 30]) * 4000 * 30)
    path = tmp_path / "wide.png"
    path.write_bytes(raw)
    fitted, mime = fit_image_path(path, "image/png")
    assert mime == "image/png"
    width, height = _png_size(fitted)
    assert width == MAX_SIDE
    assert height < 30
    assert path.read_bytes() == raw


def test_baseline_jpeg_decodes(tmp_path: Path):
    # 8×8 gray (all 128). DC category 0, then an EOB. Quant table is all ones.
    jpeg = bytes.fromhex(
        "ffd8ffdb004300010101010101010101010101010101010101010101010101"
        "01010101010101010101010101010101010101010101010101010101010101"
        "010101010101010101ffc0000b080008000801011100ffc400140000010000"
        "0000000000000000000000000000ffc4001410010000000000000000000000"
        "000000000000ffda0008010100003f001fffd9"
    )
    path = tmp_path / "gray.jpg"
    path.write_bytes(jpeg)
    fitted, mime = fit_image_path(path, "image/jpeg")
    assert mime == "image/jpeg"
    assert fitted == jpeg


def test_small_image_is_left_unchanged(tmp_path: Path):
    raw = png_bytes(32, 32, bytes([1, 2, 3]) * 32 * 32)
    path = tmp_path / "tiny.png"
    path.write_bytes(raw)
    fitted, mime = fit_image_path(path, "image/png")
    assert mime == "image/png"
    assert fitted == raw
    import base64

    b64, out_mime = fit_image_b64(base64.b64encode(raw).decode("ascii"), "image/png")
    assert out_mime == "image/png"
    assert base64.b64decode(b64) == raw
