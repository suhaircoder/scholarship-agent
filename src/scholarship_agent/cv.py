"""Read a CV on this computer and turn it into a scholarship search."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from scholarship_agent.textutil import term_in_text

_WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
_FIELDS = (
    ("computer science", "computer science"),
    ("software engineering", "software engineering"),
    ("machine learning", "machine learning"),
    ("artificial intelligence", "artificial intelligence"),
    ("data science", "data science"),
    ("civil engineering", "civil engineering"),
    ("mechanical engineering", "mechanical engineering"),
    ("electrical engineering", "electrical engineering"),
    ("chemical engineering", "chemical engineering"),
    ("mechatronics", "mechatronics"),
    ("biomedical", "biomedical"),
    ("biotechnology", "biotechnology"),
    ("molecular biology", "biology"),
    ("microbiology", "biology"),
    ("biochemistry", "chemistry"),
    ("chemistry", "chemistry"),
    ("biology", "biology"),
    ("physics", "physics"),
    ("mathematics", "mathematics"),
    ("medicine", "medicine"),
    ("nursing", "nursing"),
    ("pharmacy", "pharmacy"),
    ("public health", "public health"),
    ("architecture", "architecture"),
    ("agriculture", "agriculture"),
    ("law", "law"),
    ("education", "education"),
    ("economics", "economics"),
    ("finance", "finance"),
    ("accounting", "accounting"),
    ("psychology", "psychology"),
    ("environmental", "environmental"),
    ("robotics", "robotics"),
    ("laboratory", "laboratory"),
    ("engineering", "engineering"),
)
_SEEKING = re.compile(
    r"\b(?:seeking|applying for|looking for|objective)\b.{0,48}\b"
    r"(ph\.?\s*d\.?|doctorate|doctoral|masters?|m\.?\s?sc\.?|mba|bachelors?|undergraduate)\b",
    re.IGNORECASE | re.DOTALL,
)


MAX_CV_BYTES = 12_000_000
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".jfif")


class CvReadError(ValueError):
    """The upload could not be turned into a search."""


@dataclass(frozen=True)
class CvReading:
    degree: str
    field: str
    reason: str = ""


def read_cv(filename: str, data: bytes) -> CvReading:
    text = _text(filename, data)
    words = text.split()
    if len(words) < 8:
        raise CvReadError(
            "This file did not contain enough readable text. A PDF, a clearer photo, or a Word file works."
        )
    return interpret_cv(text)


def interpret_cv(text: str) -> CvReading:
    degree, reason = _degree(text)
    return CvReading(degree=degree, field=", ".join(_fields(text)), reason=reason)


def _degree(text: str) -> tuple[str, str]:
    """Search the next degree after the one the CV already shows."""
    seeking = _SEEKING.search(text)
    if seeking:
        return _level(seeking.group(1)), "seeking"
    if re.search(r"\bph\.?\s*d\.?\b|\bdoctorate\b|\bdoctoral\b", text, re.IGNORECASE):
        return "phd", "phd"
    if _holds_master(text) and not _current(text, "master"):
        return "phd", "completed-master"
    if _current(text, "master"):
        return "masters", "current-master"
    if _holds_bachelor(text) and not _current(text, "bachelor"):
        return "masters", "completed-bachelor"
    if _current(text, "bachelor"):
        return "bachelor", "current-bachelor"
    return "all", ""


def _holds_master(text: str) -> bool:
    return re.search(r"\bmasters?\b|\bm\.?\s?sc\.?\b|\bmba\b|\bmphil\b", text, re.IGNORECASE) is not None


def _holds_bachelor(text: str) -> bool:
    return re.search(r"\bbachelors?\b|\bb\.?\s?sc\.?\b|\bundergraduate\b", text, re.IGNORECASE) is not None


def _current(text: str, level: str) -> bool:
    if level == "master":
        degree = r"masters?|m\.?\s?sc\.?|mba|mphil"
    else:
        degree = r"bachelors?|b\.?\s?sc\.?|undergraduate"
    return (
        re.search(rf"\b(?:pursuing|enrolled in|currently)\b.{{0,40}}\b(?:{degree})\b", text, re.IGNORECASE)
        is not None
        or re.search(rf"\b(?:{degree})\s+(?:student|candidate)\b", text, re.IGNORECASE) is not None
    )


def _level(word: str) -> str:
    token = re.sub(r"[^a-z]", "", word.lower())
    if token.startswith("ph") or token.startswith("doc"):
        return "phd"
    if token.startswith("mast") or token in {"msc", "mba", "mphil"}:
        return "masters"
    return "bachelor"


def _fields(text: str) -> list[str]:
    found: list[str] = []
    for phrase, label in _FIELDS:
        if label in found:
            continue
        if label == "engineering" and any("engineering" in item for item in found):
            continue
        if term_in_text(phrase, text):
            found.append(label)
        if len(found) == 4:
            break
    return found


def _text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if data.startswith(b"%PDF") or name.endswith(".pdf"):
        return _pdf(data)
    if data.startswith(b"PK\x03\x04") or name.endswith((".docx", ".odt", ".pptx", ".xlsx")):
        packed = _zip_text(data)
        if len(packed.split()) >= 8:
            return packed
    if _is_image(name, data):
        return _image(data)
    if name.endswith(".rtf") or data.lstrip()[:5].lower() == b"{\\rtf":
        return _rtf(data)
    if name.endswith((".html", ".htm")) or data.lstrip()[:14].lower().startswith((b"<!doctype html", b"<html")):
        return _html(data)
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        return _loose_text(data)
    plain = _plain(data)
    if len(plain.split()) >= 8:
        return plain
    pages = _png_pages(data)
    if pages:
        return "\n".join(_ocr(page) for page in pages)
    return plain


def _zip_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            names = package.namelist()
            if "word/document.xml" in names:
                root = ElementTree.fromstring(package.read("word/document.xml"))
                return " ".join(node.text or "" for node in root.iter(_WORD))
            parts: list[str] = []
            total = 0
            for name in names:
                if not name.lower().endswith((".xml", ".html", ".htm", ".txt")):
                    continue
                piece = re.sub(r"<[^>]+>", " ", package.read(name).decode("utf-8", "replace"))
                parts.append(piece)
                total += len(piece)
                if total > 200_000:
                    break
            return "\n".join(parts)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise CvReadError("This file could not be read. A PDF or a photo of the CV works too.") from exc


def _pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise CvReadError("This PDF could not be read. A photo of the pages works too.") from exc
    if len(text.split()) >= 8:
        return text
    pictures: list[bytes] = []
    for page in reader.pages:
        try:
            pictures.extend(image.data for image in page.images)
        except Exception:
            continue
        if len(pictures) >= 8:
            break
    if not pictures:
        return text
    return text + "\n" + "\n".join(_image(item) for item in pictures[:8])


def _is_image(name: str, data: bytes) -> bool:
    if name.endswith(_IMAGE_SUFFIXES):
        return True
    return (
        data.startswith((b"\xff\xd8\xff", b"\x89PNG", b"GIF87a", b"GIF89a", b"BM", b"II*\x00", b"MM\x00*"))
        or (len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )


def _image(data: bytes) -> str:
    pages = _png_pages(data)
    if not pages:
        raise CvReadError("This picture could not be read. Use a JPG, PNG, or PDF.")
    return "\n".join(_ocr(page) for page in pages)


def _png_pages(data: bytes) -> list[bytes]:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise CvReadError("Picture reading is not installed.") from exc
    try:
        image = Image.open(io.BytesIO(data))
    except Exception:
        return []
    frames = 1 if image.format == "GIF" else getattr(image, "n_frames", 1)
    pages: list[bytes] = []
    for frame in range(frames):
        try:
            image.seek(frame)
        except EOFError:
            break
        page = ImageOps.exif_transpose(image).convert("RGB")
        longest = max(page.size)
        if longest > 2200:
            page.thumbnail((2200, 2200))
        elif longest < 900 and longest > 0:
            scale = 900 / longest
            page = page.resize((max(1, int(page.width * scale)), max(1, int(page.height * scale))))
        out = io.BytesIO()
        page.save(out, format="PNG")
        pages.append(out.getvalue())
        if len(pages) >= 8:
            break
    return pages


def _ocr(png: bytes) -> str:
    try:
        import asyncio

        return asyncio.run(_ocr_async(png))
    except CvReadError:
        raise
    except Exception as exc:
        raise CvReadError("This picture could not be read. Try a clearer photo or a PDF.") from exc


async def _ocr_async(png: bytes) -> str:
    try:
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    except ImportError as exc:
        raise CvReadError("This computer cannot read text from a photo. Upload a PDF instead.") from exc
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise CvReadError("This computer cannot read text from a photo. Upload a PDF instead.")
    result = await engine.recognize_async(bitmap)
    return result.text or ""


def _rtf(data: bytes) -> str:
    raw = data.decode("latin-1", "replace")
    raw = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)
    raw = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", raw)
    return raw.replace("{", " ").replace("}", " ")


def _html(data: bytes) -> str:
    raw = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", _plain(data))
    return re.sub(r"<[^>]+>", " ", raw)


def _plain(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    return data.decode("utf-8", "replace")


def _loose_text(data: bytes) -> str:
    chunks = []
    for raw in (data.decode("utf-16le", "ignore"), data.decode("latin-1", "ignore")):
        chunks.append(" ".join(re.findall(r"[A-Za-z][A-Za-z0-9.+&/' -]{2,}", raw)))
    return "\n".join(chunks)


def uploaded_file(content_type: str, body: bytes) -> tuple[str, bytes]:
    if "multipart/form-data" not in content_type or "boundary=" not in content_type:
        raise CvReadError("The upload was not a CV file.")
    marker = content_type.split("boundary=", 1)[1].strip().strip('"')
    boundary = ("--" + marker).encode()
    for part in body.split(boundary):
        if b'name="cv"' not in part and b"name='cv'" not in part:
            continue
        header, separator, data = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        filename = "cv.txt"
        match = re.search(br'filename="([^"]*)"', header)
        if match and match.group(1):
            filename = match.group(1).decode("utf-8", "replace")
        payload = data
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        if len(payload) > MAX_CV_BYTES:
            raise CvReadError("That CV is larger than 12 MB.")
        if not payload:
            raise CvReadError("Choose a CV file first.")
        return filename, payload
    raise CvReadError("Choose a CV file first.")
