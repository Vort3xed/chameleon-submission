"""Tiny axis-aligned rectangle helpers (x, y, w, h)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def x1(self) -> float:
        return self.x + self.w

    @property
    def y1(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def intersection(self, o: "Rect") -> float:
        return max(0.0, min(self.x1, o.x1) - max(self.x, o.x)) * max(0.0, min(self.y1, o.y1) - max(self.y, o.y))

    def contains(self, o: "Rect", frac: float = 0.9) -> bool:
        """True if at least `frac` of `o` lies inside self."""
        return o.area > 0 and self.intersection(o) / o.area >= frac

    def union(self, o: "Rect") -> "Rect":
        x, y = min(self.x, o.x), min(self.y, o.y)
        return Rect(x, y, max(self.x1, o.x1) - x, max(self.y1, o.y1) - y)

    def moved(self, dx: float, dy: float) -> "Rect":
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def inset(self, dx: float, dy: float | None = None) -> "Rect":
        dy = dx if dy is None else dy
        return Rect(self.x + dx, self.y + dy, max(0.0, self.w - 2 * dx), max(0.0, self.h - 2 * dy))

    def rotated_bounds(self, degrees: float) -> "Rect":
        """Axis-aligned bounds after rotating about the centre."""
        if not degrees:
            return self
        t = math.radians(degrees)
        c, s = abs(math.cos(t)), abs(math.sin(t))
        w, h = self.w * c + self.h * s, self.w * s + self.h * c
        return Rect(self.cx - w / 2, self.cy - h / 2, w, h)


def bounding(rects) -> Rect | None:
    rects = [r for r in rects if r is not None]
    if not rects:
        return None
    out = rects[0]
    for r in rects[1:]:
        out = out.union(r)
    return out
