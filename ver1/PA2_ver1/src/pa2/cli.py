from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path

from .application.import_service import ImportService
from .application.plan_service import PlanService
from .application.project_service import ProjectService
from .planning.engine import Planner
from .settings.config import AppSettings
from .storage.assets import AssetStore
from .storage.cache import CacheStore
from .storage.database import Database
from .storage.layout import DataLayout


def _runtime(data_root: Path | None):
    layout = DataLayout(data_root) if data_root else DataLayout.default()
    database = Database(layout); database.initialize()
    return layout, database, ProjectService(database), ImportService(database, AssetStore(layout), CacheStore(layout))


def doctor(_args) -> int:
    import OCP, PySide6, imageio_ffmpeg, lightgbm, sqlalchemy, vtk
    result = {
        "python": sys.version,
        "platform": sys.platform,
        "OCP": str(Path(OCP.__file__).parent),
        "PySide6": PySide6.__version__,
        "VTK": vtk.vtkVersion.GetVTKVersion(),
        "LightGBM": lightgbm.__version__,
        "SQLAlchemy": sqlalchemy.__version__,
        "FFmpeg": imageio_ffmpeg.get_ffmpeg_exe(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def analyze(args) -> int:
    layout, database, projects, imports = _runtime(args.data_root)
    project = projects.create(args.name, args.vehicle, args.product)
    settings = AppSettings()
    if args.disable_support:
        settings = replace(settings, support_enabled=False)
    result = imports.prepare(
        project.id, args.assembly, args.parts, settings, assumed_unit=args.unit,
        progress=lambda stage, message: print(f"[{stage}] {message}", file=sys.stderr),
    )
    output = {
        "project": asdict(project),
        "snapshot_id": result.snapshot.id,
        "atomic_body_count": len(result.snapshot.atomic_bodies),
        "group_count": len(result.snapshot.groups),
        "contact_count": len(result.snapshot.contacts),
        "calculation_ready": result.snapshot.calculation_ready,
        "cache": {"hits": result.cache_hits, "misses": result.cache_misses},
        "unmatched": result.grouping.unresolved_body_ids,
        "ambiguous": result.grouping.ambiguous,
        "contact_graph": next(({
            "complete": item.get("complete"),
            "candidate_count": item.get("candidate_count"),
            "unknown_pair_count": len(item.get("unknown_pairs", [])),
        } for item in result.snapshot.diagnostics if item.get("code") == "CONTACT_GRAPH"), {}),
        "elapsed_sec": result.elapsed_sec,
    }
    exit_code = 0
    if args.plan:
        if not result.snapshot.calculation_ready:
            output["planning"] = {"status": "FAILED", "reason": "접촉 그래프가 완성되지 않아 순서 생성을 시작하지 않았습니다."}
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 3
        planning = Planner(settings).generate(
            project.id, result.snapshot.project_revision, result.snapshot.id,
            result.snapshot.groups, result.snapshot.contacts, result.assembly_scene.shapes,
            base_group_id=args.base,
            progress=lambda stage, message: print(f"[{stage}] {message}", file=sys.stderr, flush=True),
            jobs_dir=layout.jobs,
        )
        output["planning"] = {
            "status": planning.status.value,
            "reason": planning.reason,
            "removal_order": planning.removal_order,
            "metrics": planning.metrics,
            "plan_id": planning.assembly_plan.id if planning.assembly_plan else None,
        }
        if planning.assembly_plan:
            PlanService(database).save_draft(planning.assembly_plan)
        exit_code = 0 if planning.status.value == "COMPLETE" else 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pa2-cli", description="PA² 진단/검증 CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("doctor", help="런타임 의존성 확인"); check.set_defaults(func=doctor)
    analysis = sub.add_parser("analyze", help="STEP 입력→그룹화→선택적 분해 탐색")
    analysis.add_argument("--assembly", type=Path, required=True)
    analysis.add_argument("--parts", type=Path, nargs="*", default=[])
    analysis.add_argument("--name", default="CLI 검증 프로젝트")
    analysis.add_argument("--vehicle", default="검증 차종")
    analysis.add_argument("--product", default="검증 품종")
    analysis.add_argument("--unit", choices=["mm", "inch"])
    analysis.add_argument("--data-root", type=Path)
    analysis.add_argument("--plan", action="store_true")
    analysis.add_argument("--base")
    analysis.add_argument("--disable-support", action="store_true")
    analysis.set_defaults(func=analyze)
    def status(args):
        from pa2.learning.collection import learning_status
        _, database, _, _ = _runtime(args.data_root)
        print(json.dumps(learning_status(database, AppSettings()), ensure_ascii=False, indent=2))
        return 0
    learning = sub.add_parser('learning-status', help='자동 수집된 계열·순서 선택 사례 수 확인')
    learning.add_argument('--data-root', type=Path); learning.set_defaults(func=status)
    def train(args):
        from pa2.learning.offline import train_recorded
        _, database, _, _ = _runtime(args.data_root)
        try:
            result = train_recorded(database, AppSettings(), args.output, pilot=args.pilot)
        except (ValueError, FileExistsError) as exc:
            print(str(exc), file=sys.stderr); return 2
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    learning_train = sub.add_parser('train-ranking', help='독립 계열 분리 오프라인 순서 학습 · 자동 적용 없음')
    learning_train.add_argument('--data-root', type=Path)
    learning_train.add_argument('--output', type=Path, required=True)
    learning_train.add_argument('--pilot', action='store_true', help='10개 계열 이상 예비 실험')
    learning_train.set_defaults(func=train)
    def cycle(args):
        from .learning.idle import _idle_worker
        from .learning.registry import ModelRegistry
        from .settings.config import SettingsStore
        import multiprocessing as mp
        import psutil
        layout, database, _, _ = _runtime(args.data_root)
        settings = SettingsStore(layout.root/'settings.json').load()
        # Explicit invocation, not a hidden startup action. The same OS lock,
        # shared snapshot and thresholds are used as the idle worker.
        context = mp.get_context('spawn')
        cancel = context.Event()
        host = psutil.Process()
        process = context.Process(target=_idle_worker, args=(str(layout.root.resolve()),
            database.engine.url.render_as_string(hide_password=False), asdict(settings),
            cancel, host.pid, host.create_time()), daemon=False)
        process.start()
        started = __import__('time').monotonic()
        try:
            while process.is_alive():
                process.join(timeout=.5)
                from .learning.idle import stop_tree
                try:
                    owner = psutil.Process(process.pid)
                    memory = sum(p.memory_info().rss for p in [owner]+owner.children(recursive=True))
                    if memory > settings.learning_memory_mb*1024**2 or __import__('time').monotonic()-started > settings.learning_budget_sec+5:
                        cancel.set();stop_tree(process);break
                except psutil.Error:
                    pass
        except KeyboardInterrupt:
            cancel.set()
            from .learning.idle import stop_tree
            stop_tree(process)
        result=ModelRegistry(database).status()
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if process.exitcode == 0 else 2
    common = sub.add_parser('learning-cycle', help='명시적 공통 순차 학습·실제 CAD 평가 (자동 적용 없음)')
    common.add_argument('--data-root', type=Path); common.set_defaults(func=cycle)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

