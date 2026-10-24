"""Text measurement that mirrors what the official renderer will draw.

The renderer (renderer/converter + cr-renderer) wraps text greedily at
spaces using per-glyph advance widths measured with skia, draws it
top-aligned inside the element box, and renders at ``int(font_size)``.
This module reproduces that exactly when skia is importable, falls back to
Pillow/FreeType advances (near-identical numbers), and finally to a
per-family average-width heuristic so the engine still works if neither
library or no font file can be found.  Nothing here may raise for bad input.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:  # exact path: same library + call the renderer uses
    import skia  # type: ignore

    _HAVE_SKIA = True
except Exception:  # pragma: no cover - depends on environment
    skia = None
    _HAVE_SKIA = False

try:
    from PIL import ImageFont  # type: ignore

    _HAVE_PIL = True
except Exception:  # pragma: no cover
    ImageFont = None
    _HAVE_PIL = False


_FONT_EXTS = {".ttf", ".otf"}
_CAMEL_SPLIT_RE = re.compile(r"(?<!^)(?=[A-Z])")
_ITALIC_RE = re.compile("italic", re.IGNORECASE)
_WEIGHTS = {"thin", "light", "extralight", "regular", "medium", "semibold", "bold", "extrabold", "black"}
_BOLD_WEIGHTS = {"bold", "semibold", "extrabold", "black"}

# Vertical metrics as a fraction of the font size, measured from the brand
# fonts with skia.  Used when no font file / library is available.
_DEFAULT_METRICS = {"ascent": 1.05, "descent": 0.35, "cap": 0.70}
_HEURISTIC_AVG_WIDTH = {"regular": 0.56, "bold": 0.60, "italic": 0.55, "bolditalic": 0.60}


def _candidate_font_dirs() -> List[Path]:
    here = Path(__file__).resolve()
    dirs = []
    env = os.environ.get("CHAMELEON_FONTS_DIR")
    if env:
        dirs.append(Path(env))
    # engine/chameleon_layout/text_metrics.py -> repo root is parents[2]
    for up in (2, 3, 1):
        try:
            dirs.append(here.parents[up] / "brand_kit" / "fonts")
        except IndexError:
            pass
    dirs.append(Path.cwd() / "brand_kit" / "fonts")
    dirs.append(Path("/app/brand_kit/fonts"))
    return dirs


def _normalize_family(name: str) -> str:
    """Same normalisation cr_renderer.fonts.normalize_family applies (minus
    its dataset-specific alias table, irrelevant for brand fonts)."""
    name = str(name or "").replace("_", " ").title()
    for token in (" Bold", " Regular", " Light", " Italic", " Medium"):
        name = name.replace(token, "")
    return name


def _suffix_to_weight_style(suffix: str) -> Tuple[str, str]:
    suffix = suffix or "Regular"
    is_italic = bool(_ITALIC_RE.search(suffix))
    weight_token = _ITALIC_RE.sub("", suffix).strip().lower() or "regular"
    weight = weight_token if weight_token in _WEIGHTS else "regular"
    if is_italic:
        style = "bolditalic" if weight == "bold" else "italic"
    else:
        style = "bold" if weight == "bold" else "regular"
    return weight, style


@dataclass
class _FontFace:
    family: str
    weight: str
    style: str
    path: Path


@lru_cache(maxsize=1)
def _font_table() -> Dict[str, List[_FontFace]]:
    """{normalized family: [faces]} built exactly like brand_fonts.py does."""
    for d in _candidate_font_dirs():
        try:
            if not d.is_dir():
                continue
            table: Dict[str, List[_FontFace]] = {}
            for path in sorted(d.glob("*")):
                if path.suffix.lower() not in _FONT_EXTS:
                    continue
                prefix, _, suffix = path.stem.partition("-")
                family = _CAMEL_SPLIT_RE.sub(" ", prefix).strip()
                weight, style = _suffix_to_weight_style(suffix)
                table.setdefault(_normalize_family(family), []).append(_FontFace(family, weight, style, path))
            if table:
                return table
        except Exception:
            continue
    return {}


def _lookup_face(family: str, weight: str, style: str) -> Optional[_FontFace]:
    """Mirror of cr_renderer FontManager.lookup's fallback chain."""
    table = _font_table()
    if not table:
        return None
    faces = table.get(_normalize_family(family)) or table.get(_normalize_family("Montserrat"))
    if not faces:
        faces = next(iter(table.values()))
    for face in faces:
        if face.weight == weight and face.style == style:
            return face
    return faces[0]


def weight_style(font_weight, font_style) -> Tuple[str, str]:
    """Replicates the converter's (weight, style) derivation."""
    w = str(font_weight or "regular").lower()
    w = w if w in _WEIGHTS else "regular"
    is_bold = w in _BOLD_WEIGHTS
    is_italic = (font_style is True) or (str(font_style or "").lower() == "italic")
    if is_bold and is_italic:
        return w, "bolditalic"
    if is_bold:
        return w, "bold"
    if is_italic:
        return w, "italic"
    return w, "regular"


@lru_cache(maxsize=64)
def _skia_typeface(path: str):
    return skia.Typeface.MakeFromData(skia.Data.MakeFromFileName(path))


@lru_cache(maxsize=4096)
def _skia_font(path: str, size: float):
    return skia.Font(_skia_typeface(path), size)


@lru_cache(maxsize=2048)
def _pil_font(path: str, size: int):
    return ImageFont.truetype(path, max(1, int(size)))


@lru_cache(maxsize=256)
def _face_metrics(path: Optional[str]) -> Tuple[float, float, float]:
    """(ascent, descent, cap height) as positive fractions of font size."""
    if path and _HAVE_SKIA:
        try:
            m = _skia_font(path, 100.0).getMetrics()
            asc, desc, cap = -m.fAscent / 100.0, m.fDescent / 100.0, m.fCapHeight / 100.0
            if asc > 0 and desc >= 0:
                return asc, desc, cap if cap > 0 else 0.7
        except Exception:
            pass
    if path and _HAVE_PIL:
        try:
            f = _pil_font(path, 100)
            asc, desc = f.getmetrics()
            return asc / 100.0, desc / 100.0, 0.70
        except Exception:
            pass
    return _DEFAULT_METRICS["ascent"], _DEFAULT_METRICS["descent"], _DEFAULT_METRICS["cap"]


_width_cache: Dict[Tuple[str, float, str], float] = {}


def char_widths(family: str, font_weight, font_style, size: float, text: str) -> List[float]:
    """Per-character advance widths, same numbers the converter wraps with."""
    if not text:
        return []
    weight, style = weight_style(font_weight, font_style)
    face = _lookup_face(family, weight, style)
    size = float(size)
    if face is not None and _HAVE_SKIA:
        try:
            font = _skia_font(str(face.path), size)
            widths = list(font.getWidths(font.textToGlyphs(text)))
            if len(widths) == len(text):
                return [float(w) for w in widths]
            # surrogate pairs etc.: fall back to per-char measurement
            out = []
            for ch in text:
                key = (str(face.path), size, ch)
                if key not in _width_cache:
                    ws = font.getWidths(font.textToGlyphs(ch))
                    _width_cache[key] = float(sum(ws))
                out.append(_width_cache[key])
            return out
        except Exception:
            pass
    if face is not None and _HAVE_PIL:
        try:
            font = _pil_font(str(face.path), int(size))
            scale = size / max(1, int(size))
            out = []
            for ch in text:
                key = (str(face.path), size, ch)
                if key not in _width_cache:
                    _width_cache[key] = float(font.getlength(ch)) * scale
                out.append(_width_cache[key])
            return out
        except Exception:
            pass
    avg = _HEURISTIC_AVG_WIDTH.get(style, 0.57) * size
    return [avg * (0.45 if ch == " " else (0.8 if ch.islower() else 1.0)) for ch in text]


def greedy_wrap(text: str, widths: List[float], max_width: float) -> str:
    """Verbatim port of renderer/converter/wrap.py::wrap_text."""
    if not text or max_width <= 0:
        return text
    chars = list(text)
    line_width = 0.0
    last_space_idx = None
    for i, c in enumerate(chars):
        if c == "\n":
            line_width = 0.0
            last_space_idx = None
            continue
        w = widths[i] if i < len(widths) else 0.0
        if line_width + w > max_width and last_space_idx is not None:
            chars[last_space_idx] = "\n"
            line_width = sum(widths[j] for j in range(last_space_idx + 1, i + 1) if chars[j] != "\n")
            last_space_idx = None
        else:
            line_width += w
        if c == " ":
            last_space_idx = i
    return "".join(chars)


@dataclass
class TextLayout:
    lines: List[str]
    line_widths: List[float]
    font_size: int
    line_height: float
    ascent: float  # fraction of font size
    descent: float
    cap: float
    widths: List[float] = field(default_factory=list, repr=False)

    @property
    def n_lines(self) -> int:
        return len(self.lines)

    @property
    def pitch(self) -> float:
        return self.font_size * self.line_height

    @property
    def max_line_width(self) -> float:
        return max(self.line_widths) if self.line_widths else 0.0

    @property
    def box_height(self) -> float:
        """Height that contains every glyph's full ascent..descent."""
        n = max(1, self.n_lines)
        return (n - 1) * self.pitch + (self.ascent + self.descent) * self.font_size

    @property
    def ink_top(self) -> float:
        """Offset from the box top to the top of tall glyphs."""
        return max(0.0, (self.ascent - 0.76) * self.font_size)

    @property
    def ink_bottom(self) -> float:
        """Offset from the box top to the bottom of descenders."""
        n = max(1, self.n_lines)
        return (n - 1) * self.pitch + (self.ascent + min(self.descent, 0.24)) * self.font_size

    @property
    def cap_center(self) -> float:
        """Offset from box top to the vertical middle of the first line's caps."""
        return (self.ascent - self.cap / 2.0) * self.font_size


def layout_text(
    content: str,
    family: str,
    font_weight,
    font_style,
    font_size: float,
    box_width: float,
    line_height: float = 1.2,
    letter_spacing: float = 0.0,
) -> TextLayout:
    """Wrap + measure ``content`` exactly like the renderer will: the
    converter wraps using advances at the float size, cr-renderer then draws
    at ``int(size)``."""
    try:
        wrap_size = float(font_size)
    except Exception:
        wrap_size = 1.0
    if not (wrap_size >= 1.0):
        wrap_size = 1.0
    size = max(1, int(wrap_size))
    content = "" if content is None else str(content)
    try:
        lh = float(line_height) if line_height else 1.2
    except Exception:
        lh = 1.2
    if not (lh > 0):
        lh = 1.2
    try:
        ls = float(letter_spacing or 0.0)
    except Exception:
        ls = 0.0
    wrap_widths = char_widths(family, font_weight, font_style, wrap_size, content)
    widths = wrap_widths if wrap_size == size else char_widths(family, font_weight, font_style, float(size), content)
    wrapped = greedy_wrap(content, wrap_widths, float(box_width))
    lines: List[str] = []
    line_widths: List[float] = []
    start = 0
    for i, ch in enumerate(wrapped + "\n"):
        if ch == "\n":
            seg = range(start, i)
            lines.append(wrapped[start:i])
            w = sum(widths[j] for j in seg if j < len(widths))
            if ls and len(seg) > 1:
                w += ls * (len(seg) - 1)
            line_widths.append(w)
            start = i + 1
    weight, style = weight_style(font_weight, font_style)
    face = _lookup_face(family, weight, style)
    asc, desc, cap = _face_metrics(str(face.path) if face else None)
    return TextLayout(lines, line_widths, size, lh, asc, desc, cap, widths)


def longest_word_width(content: str, family: str, font_weight, font_style, font_size: float, letter_spacing: float = 0.0) -> float:
    """Width of the widest unbreakable run (the renderer never breaks words)."""
    content = "" if content is None else str(content)
    widths = char_widths(family, font_weight, font_style, float(max(1, int(font_size))), content)
    best = cur = 0.0
    n = 0
    for ch, w in zip(content, widths):
        if ch in (" ", "\n"):
            best = max(best, cur + letter_spacing * max(0, n - 1))
            cur, n = 0.0, 0
        else:
            cur += w
            n += 1
    return max(best, cur + letter_spacing * max(0, n - 1))


def natural_width(content: str, family: str, font_weight, font_style, font_size: float, letter_spacing: float = 0.0) -> float:
    """Width of the text set on a single line (explicit newlines respected)."""
    content = "" if content is None else str(content)
    size = float(max(1, int(font_size)))
    best = 0.0
    for part in content.split("\n"):
        ws = char_widths(family, font_weight, font_style, size, part)
        best = max(best, sum(ws) + letter_spacing * max(0, len(part) - 1))
    return best


def backend() -> str:
    if _font_table() and _HAVE_SKIA:
        return "skia"
    if _font_table() and _HAVE_PIL:
        return "pil"
    return "heuristic"
