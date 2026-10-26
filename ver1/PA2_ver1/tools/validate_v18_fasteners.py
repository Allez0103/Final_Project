"""Read-only direction reassignment of all v17 fasteners; no path/contact checks."""
import json,time,uuid
from copy import deepcopy
from collections import Counter
from pathlib import Path

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.TopoDS import TopoDS
from diagnose_unknowns import load_inputs
from pa2.cad.brep_io import read_shape
from pa2.cad.native_worker import CadDispatcher
from pa2.cad.shapes import compound
from pa2.domain.models import PartType
from pa2.planning.fastener_direction import assigned_direction
from pa2.cad.path_check import exit_distance
from pa2.settings.config import AppSettings


def old_hint(dispatcher,gid):
    axes=[]
    for _,raw in dispatcher.face_list(dispatcher.shape(gid)):
        face=TopoDS.Face(raw); surface=BRepAdaptor_Surface(face,True)
        if surface.GetType()==GeomAbs_Cylinder:
            props=GProp_GProps(); BRepGProp.SurfaceProperties_s(face,props)
            d=surface.Cylinder().Axis().Direction()
            axes.append((abs(props.Mass()),(d.X(),d.Y(),d.Z())))
    return {'axis':max(axes,key=lambda x:x[0])[1] if axes else None}


def main():
    root=Path('runtime-data/native-validation')
    report=json.loads((root/'planning-v17-final.json').read_text(encoding='utf-8'))
    groups,files=load_inputs(report,Path('runtime-data/end-to-end-v17-final'))
    fasteners={gid:g for gid,g in groups.items() if g.part_type in (PartType.BOLT,PartType.NUT)}
    counts=Counter()
    def activity(key):
        if key not in ('BREP_FACE_BOUNDS','FASTENER_FACE_PROPERTIES'):
            raise RuntimeError('Unexpected CAD calculation: '+key)
        counts[key]+=1
    dispatcher=CadDispatcher({},activity)
    started=time.perf_counter()
    for gid,g in fasteners.items():
        dispatcher.shapes[gid]=compound([read_shape(files[bid]) for bid in g.body_ids])
        dispatcher.face_list(dispatcher.shapes[gid])
    load_elapsed=time.perf_counter()-started
    old_started=time.perf_counter()
    for gid in fasteners:old_hint(dispatcher,gid)
    old_elapsed=time.perf_counter()-old_started
    started=time.perf_counter(); hints={}
    for gid,g in fasteners.items():
        hints[gid]=dispatcher.execute('direction_policy',dict(gid=gid,neighbors=[],epsilon=.001,
            gap=.05,fastener=True,fastener_kind=g.part_type.value))
    hint_elapsed=time.perf_counter()-started
    rows=[]; started=time.perf_counter()
    paths=[p for p in report['planning']['paths'] if p['evidence'].get('evaluation_source')=='fastener_assignment']
    # Existing contact graph is read from the immutable import snapshot.
    import sqlite3
    db=sqlite3.connect(Path('runtime-data/end-to-end-v17-final/database/pa2-dev.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    contacts=[dict(r) for r in db.execute('select * from contacts where snapshot_id=?',
        (report['planning']['plan']['input_snapshot_id'],))]
    db.close()
    for item in paths:
        gid=item['group_id']; g=groups[gid]; target=groups[item['evidence']['target_group_id']]
        neighbors=set()
        for edge in contacts:
            a=edge['group_a'].split(':',1)[-1]; b=edge['group_b'].split(':',1)[-1]
            if gid==a:neighbors.add(b)
            if gid==b:neighbors.add(a)
        connected=[(groups[x],hints[x]) for x in neighbors if groups[x].part_type==PartType.BOLT]
        direction,method,linked=assigned_direction(g,target,hints[gid],connected)
        previous=tuple(item['direction'])
        rows.append(dict(group_id=gid,name=g.display_name,type=g.part_type.value,target=target.display_name,
            previous_direction=previous,removal_direction=direction,
            assembly_direction=tuple(-v for v in direction),
            changed=sum(a*b for a,b in zip(previous,direction))<.999999,
            method=method,linked_bolt_id=linked,hint=hints[gid]))
    assignment_elapsed=time.perf_counter()-started
    output=dict(ok=len(rows)==41,source_plan_unchanged=True,native_path_calls=0,
        contact_or_boolean_calls=0,fastener_hint_calls=len(hints),
        old_fastener_hint_calls=len(fasteners),shape_load_elapsed_sec=load_elapsed,
        old_hint_elapsed_sec=old_elapsed,new_hint_elapsed_sec=hint_elapsed,
        assignment_and_contact_read_elapsed_sec=assignment_elapsed,
        methods=dict(Counter(r['method'] for r in rows)),changed=sum(r['changed'] for r in rows),
        activity=dict(counts),rows=rows)
    corrected=deepcopy(report)
    corrected['planning']['plan']['id']=str(uuid.uuid4())
    by_id={r['group_id']:r for r in rows}
    steps={s['group_id']:s for s in corrected['planning']['plan']['steps']}
    remaining=set(groups)
    settings=AppSettings(**report['settings'])
    clearance=settings.resolved_for_diagonal(groups[report['planning']['plan']['base_group_id']].bounds.union(
        g.bounds for g in groups.values()).diagonal)['exit_clearance_mm']
    for gid in report['planning']['removal_order']:
        if gid in by_id:
            row=by_id[gid]; step=steps[gid]
            step['removal_direction']=row['removal_direction']; step['assembly_direction']=row['assembly_direction']
            step['travel_mm']=exit_distance(groups[gid].bounds,
                [groups[x].bounds for x in remaining-{gid}],row['removal_direction'],clearance)
            row['travel_mm']=step['travel_mm']
        remaining.remove(gid)
    corrected['direction_reassignment']={k:v for k,v in output.items() if k!='rows'}
    corrected['direction_reassignment']['scope']='v17 immutable plan copy; general search metrics inherited, not rerun; fastener signs/travel reassigned only'
    for item in corrected['planning']['paths']:
        if item['evidence'].get('evaluation_source')=='fastener_assignment':
            row=by_id[item['group_id']]
            item['direction']=row['removal_direction']; item['travel_mm']=row['travel_mm']
            item['evidence']['direction_method']=row['method']
    (root/'planning-v18-fastener-directions.json').write_text(json.dumps(corrected,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'fastener-direction-v18.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k!='rows'},ensure_ascii=False),flush=True)
    for r in rows:print(r['name'],r['previous_direction'],'->',r['removal_direction'],r['method'],flush=True)


if __name__=='__main__':main()
