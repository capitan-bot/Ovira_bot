"""QR code images (PNG bytes). WireGuard .conf files and subscription links fit; big files (OpenVPN) do not."""
import asyncio
import io

import qrcode
from qrcode.constants import ERROR_CORRECT_L
from qrcode.exceptions import DataOverflowError

MAX_FILE_BYTES = 1800


def _make(data: str) -> bytes | None:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_L, box_size=8, border=3)
    qr.add_data(data)
    try:
        qr.make(fit=True)
    except (DataOverflowError, ValueError):
        return None
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


async def make_qr(data: str) -> bytes | None:
    """None when the text is too long for a QR code."""
    return await asyncio.to_thread(_make, data)


def file_text_for_qr(content: bytes) -> str | None:
    """Text of a config file if it is small, plain UTF-8 text (so a QR scanner app can import it)."""
    if not content or len(content) > MAX_FILE_BYTES:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None
