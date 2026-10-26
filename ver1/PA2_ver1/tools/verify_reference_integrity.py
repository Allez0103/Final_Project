from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="PA² 참고자료 원본 보존 확인")
    parser.add_argument("reference_root", type=Path)
    parser.add_argument("logo", type=Path)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1]/"docs/reference_hashes.json")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    failures = []
    for relative, expected in manifest["reference_root_files"].items():
        path = args.reference_root / Path(relative)
        actual = digest(path) if path.is_file() else "MISSING"
        if actual.lower() != expected.lower():
            failures.append({"path": relative, "expected": expected, "actual": actual})
    actual_logo = digest(args.logo) if args.logo.is_file() else "MISSING"
    if actual_logo.lower() != manifest["logo_sha256"].lower():
        failures.append({"path": str(args.logo), "expected": manifest["logo_sha256"], "actual": actual_logo})
    print(json.dumps({"checked": len(manifest["reference_root_files"])+1, "ok": not failures, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

