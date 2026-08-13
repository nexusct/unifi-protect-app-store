"""Marketplace function contract + shared helpers.

A marketplace function is a single self-describing module: MANIFEST dict
(what it is, what it costs, what it needs) + a Function class implementing
process(camera, frame, ts, ctx). Customers plug a Protect API key into a
subscription; the loader instantiates whatever they've bought.
"""
import time

CATEGORIES = ["Retail & QSR", "Manufacturing & Warehouse", "Property & Liability",
              "Automotive & Parking", "Compliance", "People & Safety",
              "Healthcare & Senior Living", "Security & Access", "Intelligence"]
TIERS = ["starter", "pro", "enterprise"]


class MarketplaceFunction:
    """Base class. ctx provides: alerts, site, access_events, settings."""

    def __init__(self, settings: dict):
        self.settings = settings or {}

    def process(self, camera, frame, ts, ctx):  # pragma: no cover
        raise NotImplementedError


def validate_manifest(m: dict) -> list[str]:
    errs = []
    for key in ("id", "name", "tagline", "category", "tier"):
        if not m.get(key):
            errs.append(f"missing {key}")
    if m.get("category") and m["category"] not in CATEGORIES:
        errs.append(f"bad category {m['category']}")
    if m.get("tier") and m["tier"] not in TIERS:
        errs.append(f"bad tier {m['tier']}")
    return errs


# ── shared helpers ──────────────────────────────────────────────

def in_zone(cx, cy, polygon):
    """Ray-casting point-in-polygon (normalized coords)."""
    if not polygon:
        return False
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > cy) != (yj > cy)) and (cx < (xj - xi) * (cy - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


_model_cache = {}


def model(weights="yolov8n.pt", device="cuda"):
    if weights not in _model_cache:
        from ultralytics import YOLO
        m = YOLO(weights)
        m.to(device)
        _model_cache[weights] = m
    return _model_cache[weights]


def boxes_of(frame, weights="yolov8n.pt", classes=None, conf=0.45, device="cuda"):
    """[(cls_name, cx_norm, cy_norm, x1,y1,x2,y2, track_id|None)]"""
    import os
    w = weights if os.path.exists(weights) else "yolov8n.pt"
    res = model(w, device).track(frame, verbose=False, conf=conf, persist=True,
                                 classes=classes, tracker="bytetrack.yaml")[0]
    h, wpx = frame.shape[:2]
    out = []
    names = {k: str(v).lower() for k, v in (res.names or {}).items()}
    for box in res.boxes or []:
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        out.append((
            names.get(int(box.cls[0]), ""),
            (x1 + x2) / 2 / wpx, (y1 + y2) / 2 / h,
            x1, y1, x2, y2,
            int(box.id[0]) if box.id is not None else None,
        ))
    return out


class ZoneTracker:
    """Per-track-id zone dwell/approach state."""

    def __init__(self):
        self.state = {}

    def update(self, key, inside: bool, ts: float):
        st = self.state.setdefault(key, {"in": False, "since": None, "visits": []})
        entered = inside and not st["in"]
        dwell = (ts - st["since"]) if (inside and st["since"]) else 0
        if entered:
            st["since"] = ts
            st["visits"].append(ts)
        if not inside:
            st["since"] = None
        st["in"] = inside
        return entered, dwell, st


def crossed_line(p_prev, p_now, line):
    """Direction-aware segment crossing. line = [(x1,y1),(x2,y2)] normalized."""
    (x1, y1), (x2, y2) = line

    def side(p):
        return (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1)

    a, b = side(p_prev), side(p_now)
    if a == 0 or b == 0 or (a > 0) == (b > 0):
        return 0
    return 1 if a < 0 else -1
