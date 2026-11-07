"""Read-only photo metadata from file headers.

Only headers are read (EXIF via exifread, PNG/GIF size fields); macOS tools are
called with absolute paths and a timeout. GPS coordinates and camera serial
numbers are returned for in-memory grouping only: callers must never store them
in plan items, profiles, descriptions or diagnostics.
"""

import logging
import os
import re
import struct
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

SIPS = "/usr/bin/sips"
MDLS = "/usr/bin/mdls"
TOOL_TIMEOUT = 5
EXIF_EXTENSIONS = {"jpg", "jpeg", "heic", "heif", "tif", "tiff", "webp", "png", "dng", "cr2", "nef", "arw"}
SCREENSHOT_NAME = re.compile(
    r"^(screenshot|screen shot|bildschirmfoto|capture d.?(e|é)cran|schermata|captura de pantalla|cleanshot)\b",
    re.IGNORECASE,
)
DATE_TAGS = ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime")

logging.getLogger("exifread").setLevel(logging.ERROR)


def _tool(path: str) -> bool:
    return sys.platform == "darwin" and os.path.isfile(path) and os.access(path, os.X_OK)


def parse_exif_date(value: Any) -> Optional[datetime]:
    text = str(value or "").strip().replace("-", ":")
    if not text:
        return None
    try:
        parsed = datetime.strptime(text[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if not 1970 <= parsed.year <= datetime.now().year + 1:
        return None
    return parsed


def _ratio(value: Any) -> float:
    numerator = getattr(value, "num", None)
    denominator = getattr(value, "den", None)
    if numerator is not None and denominator:
        return float(numerator) / float(denominator)
    return float(value)


def _gps(tags: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    try:
        lat_parts = tags["GPS GPSLatitude"].values
        lon_parts = tags["GPS GPSLongitude"].values
        lat = sum(_ratio(part) / (60 ** index) for index, part in enumerate(lat_parts[:3]))
        lon = sum(_ratio(part) / (60 ** index) for index, part in enumerate(lon_parts[:3]))
        if str(tags.get("GPS GPSLatitudeRef", "N")).strip().upper().startswith("S"):
            lat = -lat
        if str(tags.get("GPS GPSLongitudeRef", "E")).strip().upper().startswith("W"):
            lon = -lon
    except (KeyError, AttributeError, TypeError, ValueError, ZeroDivisionError, IndexError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return round(lat, 5), round(lon, 5)


def _int_tag(tags: Dict[str, Any], *names: str) -> Optional[int]:
    for name in names:
        value = tags.get(name)
        if value is None:
            continue
        try:
            number = int(str(value).split()[0])
        except (ValueError, IndexError):
            continue
        if number > 0:
            return number
    return None


def _read_exif(path: Path) -> Dict[str, Any]:
    try:
        import exifread
    except ImportError:  # pragma: no cover - exifread ships in the build
        return {}
    try:
        with path.open("rb") as handle:
            return exifread.process_file(handle, details=False) or {}
    except Exception:
        # exifread raises a wide variety of errors on malformed headers.
        return {}


def _header_size(path: Path) -> Tuple[Optional[int], Optional[int]]:
    try:
        with path.open("rb") as handle:
            head = handle.read(32)
    except OSError:
        return None, None
    if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
        width, height = struct.unpack(">II", head[16:24])
        return width or None, height or None
    if head[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", head[6:10])
        return width or None, height or None
    return None, None


def _sips_size(path: Path) -> Tuple[Optional[int], Optional[int]]:
    if not _tool(SIPS):
        return None, None
    try:
        output = subprocess.run(
            [SIPS, "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None, None
    width = re.search(r"pixelWidth:\s*(\d+)", output)
    height = re.search(r"pixelHeight:\s*(\d+)", output)
    return (int(width.group(1)) if width else None, int(height.group(1)) if height else None)


def _mdls(path: Path, *names: str) -> Dict[str, str]:
    if not _tool(MDLS):
        return {}
    arguments = [MDLS]
    for name in names:
        arguments += ["-name", name]
    try:
        output = subprocess.run(
            arguments + [str(path)], capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    values = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            value = value.strip()
            if value and value != "(null)":
                values[key.strip()] = value.strip('"')
    return values


def looks_like_screenshot_name(name: str) -> bool:
    return bool(SCREENSHOT_NAME.match(name))


def read_meta(path: Path, use_tools: bool = True, spotlight: bool = False) -> Dict[str, Any]:
    """Return {dateTaken, dateSource, camera, width, height, isScreenshot, gps}.

    ``dateSource`` is ``taken`` when EXIF holds a usable capture date, otherwise
    ``modified`` and ``dateTaken`` is the file's modification time. ``gps`` is
    (lat, lon) or None and is for in-memory use only.
    """
    path = Path(path)
    extension = path.suffix.lower().lstrip(".")
    tags = _read_exif(path) if extension in EXIF_EXTENSIONS else {}
    taken = None
    for name in DATE_TAGS:
        taken = parse_exif_date(tags.get(name))
        if taken:
            break
    if taken:
        date_source = "taken"
    else:
        try:
            taken = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            taken = None
        date_source = "modified"
    camera = str(tags.get("Image Model", "") or "").strip() or None
    width = _int_tag(tags, "EXIF ExifImageWidth", "Image ImageWidth")
    height = _int_tag(tags, "EXIF ExifImageLength", "Image ImageLength")
    if not width or not height:
        width, height = _header_size(path)
    if (not width or not height) and use_tools and extension in EXIF_EXTENSIONS:
        width, height = _sips_size(path)
    gps = _gps(tags)
    screenshot = looks_like_screenshot_name(path.name)
    if spotlight and use_tools:
        values = _mdls(path, "kMDItemIsScreenCapture", "kMDItemLatitude", "kMDItemLongitude")
        screenshot = screenshot or values.get("kMDItemIsScreenCapture") == "1"
        if gps is None and "kMDItemLatitude" in values and "kMDItemLongitude" in values:
            try:
                gps = (round(float(values["kMDItemLatitude"]), 5), round(float(values["kMDItemLongitude"]), 5))
            except ValueError:
                gps = None
    return {
        "dateTaken": taken.isoformat() if taken else None,
        "dateSource": date_source,
        "camera": camera,
        "width": width,
        "height": height,
        "isScreenshot": screenshot,
        "gps": gps,
    }
