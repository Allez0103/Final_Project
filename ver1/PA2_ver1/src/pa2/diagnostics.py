"""Native worker smoke check usable from a packaged Windows executable."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeCone
from OCP.gp import gp_Pnt

from .cad.contacts import ContactService
from .domain.models import AssemblyGroup, Bounds, MatchingStatus, PartType, GeometryStatus
from .planning.engine import Planner
from .settings.config import AppSettings


def native_smoke(output: str) -> int:
    destination=Path(output).resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    groups=[AssemblyGroup(str(i),str(i),[str(i)],PartType.UNKNOWN,Bounds(i,0,0,i+1,1,1),
                          1.0,(i+.5,.5,.5),True,MatchingStatus.UNMATCHED) for i in range(2)]
    shapes={str(i):BRepPrimAPI_MakeBox(gp_Pnt(i,0,0),1,1,1).Shape() for i in range(2)}
    try:
        contacts=ContactService().build(groups,[],SimpleNamespace(shapes=shapes),jobs_dir=destination.parent/"jobs")
        result=Planner(AppSettings()).generate("smoke",1,"smoke",groups,contacts.edges,shapes,"0",jobs_dir=destination.parent/"jobs")
        root=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[2]))
        report={"contact_complete":contacts.complete,"contact_count":len(contacts.edges),
                "planning_status":result.status.value,"steps":len(result.assembly_plan.steps),
                "logo_exists":(root/"assets/thn_logo.png").is_file(),"metrics":result.metrics}
        report["ok"]=contacts.complete and len(contacts.edges)==1 and result.status.value=="COMPLETE" and report["logo_exists"]
        bolt=AssemblyGroup("bolt","BLT-smoke",["bolt"],PartType.BOLT,Bounds(-1,-1,0,1,1,3),9.42478,(0,0,1.5),True)
        body=AssemblyGroup("body","MBD-smoke",["body"],PartType.BODY,Bounds(-3,-3,-2,3,3,1),108,(0,0,-.5),True)
        bolt_result=Planner(AppSettings()).generate("smoke",1,"smoke",[body,bolt],[],
            {"body":BRepPrimAPI_MakeBox(gp_Pnt(-3,-3,-2),6,6,3).Shape(),"bolt":BRepPrimAPI_MakeCylinder(1,3).Shape()},
            "body",jobs_dir=destination.parent/"jobs")
        report["initial_decrease_status"]=bolt_result.status.value
        report["initial_decrease_steps"]=bolt_result.metrics["initial_decrease_exception_steps"]
        report['fastener_assigned_steps']=bolt_result.metrics['fastener_assigned_steps']
        report['fastener_path_calls']=bolt_result.metrics['native_path_calls']
        report["ok"] = report["ok"] and bolt_result.status.value=="REVIEW_REQUIRED" and bolt_result.assembly_plan.steps[0].geometry_status==GeometryStatus.FASTENER_ASSIGNED and report['fastener_assigned_steps']==1 and report['fastener_path_calls']==0
        # Put the target above the bolt so the old center-away sign is wrong.
        from .cad.shapes import compound
        from OCP.gp import gp_Ax2,gp_Dir
        headed=compound([BRepPrimAPI_MakeCylinder(1,3).Shape(),
            BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0,0,3),gp_Dir(0,0,1)),2,1).Shape()])
        from dataclasses import replace
        above=replace(body,bounds=Bounds(-3,-3,6,3,3,9),centroid=(0,0,7.5))
        head_result=Planner(AppSettings()).generate('head-smoke',1,'s',[above,bolt],[],
            {'body':BRepPrimAPI_MakeBox(gp_Pnt(-3,-3,6),6,6,3).Shape(),'bolt':headed},
            'body',jobs_dir=destination.parent/'jobs')
        report['head_side_removal_direction']=head_result.assembly_plan.steps[0].removal_direction
        report['head_side_assembly_direction']=head_result.assembly_plan.steps[0].assembly_direction
        report['head_side_path_calls']=head_result.metrics['native_path_calls']
        report['head_side_method']=next(p.evidence['direction_method'] for p in head_result.path_results)
        report['ok']=report['ok'] and report['head_side_removal_direction']==(0,0,1) and report['head_side_path_calls']==0
        bolt.part_type=PartType.SEAL
        seal_result=Planner(AppSettings()).generate("smoke",1,"smoke",[body,bolt],[],
            {"body":BRepPrimAPI_MakeBox(gp_Pnt(-3,-3,-2),6,6,3).Shape(),"bolt":BRepPrimAPI_MakeCylinder(1,3).Shape()},
            "body",jobs_dir=destination.parent/"jobs")
        report["nonbolt_initial_decrease_steps"]=seal_result.metrics["initial_decrease_exception_steps"]
        report["ok"] = report["ok"] and seal_result.status.value=="REVIEW_REQUIRED" and len(seal_result.assembly_plan.steps)==1
        from .cad.path_check import ConservativePathChecker
        from .cad.sweep import bounds
        cone=BRepPrimAPI_MakeCone(2,1,2).Shape()
        floor=BRepPrimAPI_MakeBox(gp_Pnt(-3,-3,-1),6,6,1).Shape()
        curve_groups=[AssemblyGroup(name,name,[name],PartType.UNKNOWN,bounds(shape),1,None,True)
                      for name,shape in (("cone",cone),("floor",floor))]
        curve=ConservativePathChecker(.001,.001,30,initial_overlap_region_enabled=True).check(
            curve_groups[0],cone,[(curve_groups[1],floor)],(0,0,1),3,{"cone","floor"})
        report["curved_sweep_decision"]=curve.decision.value
        report["path_policy_version"]=curve.policy_version
        report["ok"] = report["ok"] and curve.decision.value=="PASS"
    except Exception as exc:
        report={"ok":False,"error":f"{type(exc).__name__}: {exc}"}
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0 if report["ok"] else 1
