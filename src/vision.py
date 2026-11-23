"""All image coordinates are normalized to a 1920 x 1080 client image."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def normalize(frame):
    h, w = frame.shape[:2]
    if abs(w / h - 16 / 9) > 0.035:
        raise ValueError("游戏画面需为 16:9，请检查是否有黑边或窗口边框")
    return cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_AREA)


def compact(text):
    return re.sub(r"[\s,，]", "", text)


def auto_battle_enabled(frame):
    # The enabled arrows rotate; their gold color remains stable.
    icon = cv2.cvtColor(frame[50:101, 145:195], cv2.COLOR_BGR2HSV)
    return cv2.countNonZero(cv2.inRange(icon, (12, 110, 150), (40, 255, 255))) >= 200


@dataclass(frozen=True)
class Hit:
    x: int
    y: int
    score: float


class Templates:
    def __init__(self):
        self.meta = json.loads((ROOT / "assets/templates.json").read_text(encoding="utf-8"))
        self.images = {name: cv2.imread(str(ROOT / "assets" / (name + ".png")))
                       for name in self.meta}
        if any(value is None for value in self.images.values()):
            raise RuntimeError("识别素材缺失")
        self.stats = {"count": 0, "seconds": 0.0}

    def measured(self, started):
        self.stats["count"] += 1
        self.stats["seconds"] += time.perf_counter()-started

    def find(self, frame, name, region=None, threshold=None):
        started = time.perf_counter()
        info = self.meta[name]
        x1, y1, x2, y2 = region or info["search"]
        crop = frame[y1:y2, x1:x2]
        template = self.images[name]
        if crop.shape[0] < template.shape[0] or crop.shape[1] < template.shape[1]:
            self.measured(started)
            return None
        result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
        _, confidence, _, location = cv2.minMaxLoc(result)
        if confidence < (threshold if threshold is not None else info.get("threshold", 0.86)):
            self.measured(started)
            return None
        self.measured(started)
        return Hit(x1 + location[0] + template.shape[1] // 2,
                   y1 + location[1] + template.shape[0] // 2, confidence)

    def popup_close(self, frame):
        candidates = [hit for name in ("popup_close_dark", "popup_close_light", "popup_close_panel", "popup_close_tribute", "popup_close_costume")
                      if name in self.meta
                      for hit in self.all(frame, name, self.meta[name]["search"], threshold=0.88)]
        if not candidates:
            return None
        candidates.sort(key=lambda hit: hit.score, reverse=True)
        best = candidates[0]
        if any(abs(hit.x-best.x) > 20 or abs(hit.y-best.y) > 20 for hit in candidates[1:]):
            return None
        return best

    def all(self, frame, name, region, threshold=0.87):
        started = time.perf_counter()
        x1, y1, x2, y2 = region
        template = self.images[name]
        result = cv2.matchTemplate(frame[y1:y2, x1:x2], template, cv2.TM_CCOEFF_NORMED)
        hits = []
        while True:
            _, confidence, _, location = cv2.minMaxLoc(result)
            if confidence < threshold:
                self.measured(started)
                return hits
            x, y = location
            hits.append(Hit(x1+x+template.shape[1]//2, y1+y+template.shape[0]//2, confidence))
            radius = max(template.shape[:2])
            result[max(0,y-radius):y+radius, max(0,x-radius):x+radius] = -1


def parse_attempts(text):
    match = re.search(r"([0-3])/3", compact(text))
    return int(match[1]) if match else None


def valid_contract(text, coin_found):
    text = compact(text)
    return coin_found and re.search(r"A级契约[券卷]", text) is not None and re.search(r"(?<!\d)6000(?!\d)", text) is not None and not any(
        word in text for word in ("USD", "充值", "蝴蝶", "$")) and not contract_unavailable(text)


def contract_unavailable(text):
    text = compact(text)
    return any(word in text for word in ("无库存", "售罄", "SoldOut")) \
        or re.search(r"剩余数量[:：]0(?:/1)?(?:\D|$)", text) is not None


def parse_score(text):
    value = compact(text)
    return int(value) if re.fullmatch(r"\d{1,3}", value) else None


def is_sign_in_claim(text):
    # OCR can omit the first 一 in the observed 一键领取 label.
    return re.fullmatch(r"(?:一?键)?领取|全部领取", compact(text)) is not None


def select_coin_wishes(coin_hits, completed_hits):
    # Completed stamps sit to the left of the reward icon on each map node.
    return [hit for hit in sorted(coin_hits, key=lambda h: (h.y, h.x))
            if not any(abs(hit.x-done.x) < 80 and abs(hit.y-done.y) < 80
                       for done in completed_hits)]
