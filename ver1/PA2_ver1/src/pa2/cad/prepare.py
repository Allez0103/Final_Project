"""Bounded parameter-consistency repair on private calculation copies only."""
from __future__ import annotations
import math
from dataclasses import asdict
from OCP.BRep import BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepLib import BRepLib
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE,TopAbs_FACE,TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from .sweep import bounds


# Calculation-copy repair limits; independent of collision/distance epsilon.
REPAIR_MAX_TOLERANCE_MM = 0.01
REPAIR_MAX_RELATIVE_VOLUME_CHANGE = 1e-5  # 0.001 percent
REPAIR_POLICY_VERSION = 'parameter-repair-v2-bounded'


def _properties(shape):
    tolerances=[];counts=[]
    for kind,cast in ((TopAbs_EDGE,TopoDS.Edge),(TopAbs_FACE,TopoDS.Face),(TopAbs_VERTEX,TopoDS.Vertex)):
        ex=TopExp_Explorer(shape,kind);count=0
        while ex.More():
            tolerances.append(BRep_Tool.Tolerance_s(cast(ex.Current())));count+=1;ex.Next()
        counts.append(count)
    props=GProp_GProps();BRepGProp.VolumeProperties_s(shape,props)
    return abs(props.Mass()),max(tolerances,default=math.inf),bounds(shape),counts


def prepare(shape,epsilon,activity):
    activity('BREP_INPUT_VALIDATION')
    if BRepCheck_Analyzer(shape,True).IsValid():return shape,None,True
    evidence={'code':'INPUT_GEOMETRY_INVALID','repair':'SAME_PARAMETER','accepted':False,
              'repair_policy_version':REPAIR_POLICY_VERSION}
    try:
        topology_valid=BRepCheck_Analyzer(shape,False).IsValid()
        evidence['topology_valid_before']=topology_valid
        if not topology_valid:return shape,evidence,False
        before,tol0,box0,counts0=_properties(shape)
        repaired=BRepBuilderAPI_Copy(shape,True,False).Shape()
        activity('BREP_PARAMETER_REPAIR')
        BRepLib.SameParameter_s(repaired,min(1e-7,epsilon/10),True)
        activity('BREP_REPAIR_VALIDATION')
        valid=BRepCheck_Analyzer(repaired,True).IsValid()
        after,tol1,box1,counts1=_properties(repaired)
        delta=max(abs(a-b) for a,b in zip(asdict(box0).values(),asdict(box1).values()))
        volume_limit=max(1e-9,before*REPAIR_MAX_RELATIVE_VOLUME_CHANGE)
        checks={'geometry_valid_after':valid,
                'volume_finite_positive':before>0 and math.isfinite(after),
                'tolerance_within_limit':tol1<=REPAIR_MAX_TOLERANCE_MM,
                'bounds_within_limit':delta<=epsilon,
                'counts_unchanged':counts0==counts1,
                'volume_change_within_limit':abs(after-before)<=volume_limit}
        evidence.update({'volume_before_mm3':before,'volume_after_mm3':after,'max_tolerance_before_mm':tol0,
            'max_tolerance_after_mm':tol1,'max_bounds_change_mm':delta,'epsilon_mm':epsilon,
            'repair_max_tolerance_mm':REPAIR_MAX_TOLERANCE_MM,
            'repair_max_relative_volume_change':REPAIR_MAX_RELATIVE_VOLUME_CHANGE,
            'repair_max_volume_change_mm3':volume_limit,'checks':checks})
        accepted=all(checks.values())
        if accepted:
            evidence.update({'code':'INPUT_PARAMETER_REPAIRED','accepted':True})
            return repaired,evidence,True
        return shape,evidence,False
    except InterruptedError:raise
    except Exception as exc:
        evidence['error']=f'{type(exc).__name__}: {exc}'
        return shape,evidence,False
