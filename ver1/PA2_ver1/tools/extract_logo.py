"""Extract the approved top-left THN lockup without resampling or recoloring.

The source is never modified. The crop coordinates are pinned to source SHA-256
70B68FE3C418C1A0EF9C0E1DCC097F8B318F93C66CA739E937BCFCCC1F1F27BB.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from PIL import Image


EXPECTED = "70b68fe3c418c1a0ef9c0e1dcc097f8b318f93c66ca739e937bcfccc1f1f27bb"
CROP = (64, 0, 330, 76)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if hashlib.sha256(args.source.read_bytes()).hexdigest() != EXPECTED:
        raise SystemExit("알 수 없는 로고 원본입니다. 자동 추출하지 않았습니다.")
    with Image.open(args.source) as image:
        if image.size != (591, 459):
            raise SystemExit("로고 원본 크기가 달라 자동 추출하지 않았습니다.")
        result = image.convert("RGBA").crop(CROP)
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        result.save(args.destination, format="PNG", optimize=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

