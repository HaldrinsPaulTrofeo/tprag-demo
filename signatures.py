"""Content-addressed store for e-signature and barangay seal images.

Each image is decoded, re-encoded as PNG (dropping metadata and anything that is
not a picture) and saved under its SHA-256. A file is never overwritten, so a
request that recorded a hash keeps showing exactly the signature it was signed
with, even after the signer uploads a new one.
"""
import base64
import hashlib
import io
from pathlib import Path

from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

STORE = Path(__file__).resolve().parent / "private_uploads" / "signatures"
MAX_BYTES = 3 * 1024 * 1024
LIMITS = {"signature": (900, 300), "seal": (400, 400)}


class ImageRejected(ValueError):
    pass


def save_image(data: bytes, kind: str) -> str:
    if kind not in LIMITS:
        raise ValueError("unknown image kind")
    if not data:
        raise ImageRejected("The file is empty.")
    if len(data) > MAX_BYTES:
        raise ImageRejected("The image is larger than 3 MB.")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ("PNG", "JPEG"):
            raise ImageRejected("Upload a PNG or JPG image.")
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ImageRejected("That file is not a readable PNG or JPG image.")
    img = ImageOps.exif_transpose(img).convert("RGBA")
    if kind == "signature":
        img = _ink_only(img)
    img.thumbnail(LIMITS[kind])
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    png = out.getvalue()
    key = hashlib.sha256(png).hexdigest()
    STORE.mkdir(parents=True, exist_ok=True)
    path = STORE / f"{key}.png"
    if not path.exists():
        path.write_bytes(png)
    return key


def _ink_only(img):
    """Make paper transparent and crop to the ink, so the signature sits on the line.

    Phone photos of paper are grey, not white: stretch contrast first so the
    paper reaches white and the pen stays dark.
    """
    img.thumbnail((1800, 1800))
    gray = ImageOps.autocontrast(img.convert("L"), cutoff=2)
    ink = gray.point(lambda v: 0 if v > 200 else 255 if v <= 140 else int((200 - v) * 255 / 60))
    alpha = ImageChops.multiply(img.getchannel("A"), ink)
    if alpha.getbbox() is None:
        raise ImageRejected("No signature was found in the image. Sign on white paper with a dark pen.")
    out = img.copy()            # keeps the pen's own colour (often blue)
    out.putalpha(alpha)
    return out.crop(alpha.getbbox())


def data_uri(key):
    if not key or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        return None
    path = STORE / f"{key}.png"
    if not path.exists():
        return None
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
