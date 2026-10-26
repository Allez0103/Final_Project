from __future__ import annotations

import time
from dataclasses import dataclass, field

from pa2.domain.models import AssemblyGroup, AtomicBody, ContactEdge
from pa2.jobs.isolated import NativeCallError

from .importer import CadScene
from .isolated import NativeCadSession


@dataclass(slots=True)
class ContactGraphResult:
    edges: list[ContactEdge]
    complete: bool
    unknown_pairs: list[tuple[str, str]] = field(default_factory=list)
    candidate_count: int = 0
    failures: list[dict] = field(default_factory=list)


class ContactService:
    VERSION = "contact-v3-binary-brep"

    def __init__(self, gap_mm: float = 0.05, native_timeout_sec: float = 120) -> None:
        self.gap_mm = gap_mm
        self.native_timeout_sec = native_timeout_sec

    def build(self, groups: list[AssemblyGroup], bodies: list[AtomicBody], scene: CadScene, *,
              cancel_check=lambda: False, progress=lambda *_: None, deadline=None, jobs_dir=None) -> ContactGraphResult:
        edges: list[ContactEdge] = []
        ordered = sorted(groups, key=lambda group: group.id)
        candidates: list[tuple[AssemblyGroup, AssemblyGroup]] = []
        for index, a in enumerate(ordered):
            for b in ordered[index + 1:]:
                if a.bounds.expanded(self.gap_mm).intersects(b.bounds):
                    candidates.append((a, b))
        unknown: list[tuple[str, str]] = []
        failures = []
        if not candidates:
            return ContactGraphResult([], True)
        with NativeCadSession(groups, scene.shapes, native_timeout=self.native_timeout_sec,
                              cancel_check=cancel_check, jobs_dir=jobs_dir) as worker:
            for index, (a, b) in enumerate(candidates):
                if cancel_check():
                    raise InterruptedError("접촉 계산을 취소했습니다.")
                if deadline is not None and time.monotonic() >= deadline:
                    unknown.extend((x.id, y.id) for x, y in candidates[index:])
                    failures.append({"reason": "TIME_BUDGET_EXCEEDED", "remaining_count": len(candidates)-index})
                    break
                progress("contacts", f"접촉 확인 {index+1}/{len(candidates)} · {a.display_name} / {b.display_name}")
                started = time.perf_counter()
                try:
                    value = worker.call("distance", {"groups": (a.id,b.id), "gap": self.gap_mm}, deadline=deadline)
                except NativeCallError as exc:
                    unknown.append((a.id, b.id))
                    failures.append({"pair": [a.id, b.id], "reason": str(exc)})
                    progress("contacts", f"접촉 확인 {index+1}/{len(candidates)} 미판정: {exc}")
                    continue
                if value <= self.gap_mm:
                    edges.append(ContactEdge(
                        group_a=a.id,
                        group_b=b.id,
                        distance_mm=value,
                        evidence={"method": "BREP_SOLID_PAIR_CONTACT_WITNESS", "elapsed_sec": time.perf_counter()-started},
                        policy_version=self.VERSION,
                    ))
        return ContactGraphResult(edges, not unknown, unknown, len(candidates), failures)

