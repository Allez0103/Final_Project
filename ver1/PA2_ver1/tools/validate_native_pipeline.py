"""Reopen a managed snapshot, refresh contacts, and optionally validate planning."""
from __future__ import annotations

import argparse
import json
import multiprocessing
import time
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from pa2.cli import _runtime
from pa2.planning.engine import Planner
from pa2.settings.config import AppSettings
from pa2.cad.importer import StepImporter
from pa2.cad.path_check import ConservativePathChecker
from pa2.cad.prepare import (REPAIR_POLICY_VERSION, REPAIR_MAX_TOLERANCE_MM,
                             REPAIR_MAX_RELATIVE_VOLUME_CHANGE)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-root",type=Path,required=True)
    parser.add_argument("--project")
    parser.add_argument("--assembly", type=Path)
    parser.add_argument("--parts", type=Path, nargs='*', default=[])
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--plan",action="store_true")
    parser.add_argument("--budget",type=int,default=3600)
    parser.add_argument("--native-timeout",type=int,default=120)
    parser.add_argument("--candidate-timeout",type=int,default=AppSettings().candidate_timeout_sec)
    parser.add_argument("--disable-support",action="store_true")
    parser.add_argument("--strict-initial-overlap",action="store_true")
    parser.add_argument("--strict-support",action="store_true")
    parser.add_argument('--exception-name',action='append',default=[])
    parser.add_argument('--cad-threads',type=int,default=AppSettings().cad_boolean_threads)
    args=parser.parse_args()
    settings=replace(AppSettings(),generation_timeout_sec=args.budget,
                     native_operation_timeout_sec=args.native_timeout,
                     candidate_timeout_sec=args.candidate_timeout,support_enabled=not args.disable_support,
                     cad_boolean_threads=args.cad_threads,
                     bolt_initial_overlap_enabled=not args.strict_initial_overlap,
                     initial_overlap_region_enabled=not args.strict_initial_overlap,
                     allow_support_unknown_draft=not args.strict_support)
    settings.validate()
    layout,db,projects,imports=_runtime(args.data_root)
    started=time.monotonic()
    if args.assembly:
        project=projects.create('v17 최종 보완·전체 검증', 'KD1', 'HVJB')
        args.project=project.id
        result=imports.prepare(project.id,args.assembly,args.parts,settings,
            progress=lambda stage,msg:print(f"[{stage}] {msg}",flush=True))
    elif args.project:
        result=imports.reopen(args.project)
    else:
        parser.error('--assembly or --project is required')
    print(f"REOPEN groups={len(result.snapshot.groups)}",flush=True)
    imports.ensure_contacts(result,settings,progress=lambda stage,msg:print(f"[{stage}] {msg}",flush=True))
    contact_time=time.monotonic()-started
    output={"project_id":args.project,"shape_cache_version":StepImporter.VERSION,
            "path_policy_version":ConservativePathChecker.VERSION,"planner_version":Planner.VERSION,"settings":asdict(settings),
            "repair_policy":{"version":REPAIR_POLICY_VERSION,"max_tolerance_mm":REPAIR_MAX_TOLERANCE_MM,
                             "max_relative_volume_change":REPAIR_MAX_RELATIVE_VOLUME_CHANGE},
            "group_count":len(result.snapshot.groups),"contact_count":len(result.snapshot.contacts),
            "calculation_ready":result.snapshot.calculation_ready,"contact_elapsed_sec":contact_time,
            "fresh_import": bool(args.assembly), "shape_cache_hits": result.cache_hits,
            "shape_cache_misses": result.cache_misses,
            "contact_graph":next(item for item in result.snapshot.diagnostics if item.get("code")=="CONTACT_GRAPH")}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"CONTACT_COMPLETE ready={result.snapshot.calculation_ready} edges={len(result.snapshot.contacts)} elapsed={contact_time:.2f}",flush=True)
    if args.plan and result.snapshot.calculation_ready:
        exceptions=[]
        for name in args.exception_name:
            matches=[g.id for g in result.snapshot.groups if g.display_name==name]
            if len(matches)!=1:raise ValueError(f'예외 이름을 유일하게 찾지 못했습니다: {name}: {matches}')
            exceptions.extend(matches)
        from pa2.application.plan_service import PlanService
        base=Planner.choose_base([g for g in result.snapshot.groups if g.id not in exceptions])
        PlanService(db).save_preset(args.project,result.snapshot.id,base,exceptions)
        plan=Planner(settings).generate(args.project,result.snapshot.project_revision,result.snapshot.id,
            result.snapshot.groups,result.snapshot.contacts,result.assembly_scene.shapes,
            progress=lambda stage,msg:print(f"[{stage}] {msg}",flush=True),jobs_dir=layout.jobs,
            collision_exception_ids=exceptions)
        output["planning"]={"status":plan.status.value,"reason":plan.reason,"metrics":plan.metrics,
            "reason_counts":dict(Counter(item.reason_code for item in plan.path_results)),
            "removal_order":plan.removal_order,
            "paths":[asdict(item) for item in plan.path_results],"plan":plan.assembly_plan.to_dict()}
        output['total_import_contact_planning_elapsed_sec']=time.monotonic()-started
        args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
        brief={key:value for key,value in output["planning"].items() if key not in {"paths","plan"}}
        brief['metrics']={key:value for key,value in plan.metrics.items() if key not in ('virtual_paths','direction_hints')}
        print(json.dumps(brief,ensure_ascii=False),flush=True)
    return 0


if __name__=="__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
