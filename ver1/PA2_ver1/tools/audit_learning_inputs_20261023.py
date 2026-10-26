"""Read-only dataset/recognition suitability audit. Never executes supplied scripts or trains."""
import hashlib,json,time,traceback
from collections import Counter,defaultdict
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from pa2.cad.importer import StepImporter
from pa2.cad.grouping import GroupingService
from pa2.domain.classification import classify_part
from pa2.learning.collection import family_fingerprint
from pa2.planning.priority import is_fastener
from pa2.settings.config import AppSettings

ROOT=Path(__file__).resolve().parents[1]
INPUT=Path('C:/Users/Win11Pro/Desktop/data_example/learning')
OUT=ROOT/'runtime-data/learning-input-audit-20261023'


def read(path,default=None):return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else default
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def labels(folder):
    manifest=read(folder/'labels/assembly_manifest.json',{})
    sequence=read(folder/'labels/assembly_sequence.json',{})
    card=read(folder/'labels/dataset_card.json',{})
    definitions=manifest.get('definitions',[]);instances=manifest.get('instances',[])
    definition_map={d['part_id']:d for d in definitions}
    instance_map={i['instance_id']:i for i in instances}
    operations=read(folder/'metadata/operations.json',[])
    if sequence.get('sequence') is not None:operations=sequence['sequence'];ids=[o.get('unit_id') for o in operations]
    else:
        op_map={o['operation_id']:o for o in operations}
        ids=sequence.get('operation_ids',[]);operations=[op_map.get(i,{'operation_id':i,'missing':True}) for i in ids]
    general=[];axis=Counter();missing=[];seen=[];multi=[]
    for op in operations:
        member_ids=op.get('instance_ids',[])
        seen.extend(member_ids)
        fasteners=[]
        for iid in member_ids:
            inst=instance_map.get(iid)
            if not inst:missing.append(iid);continue
            typ=inst.get('part_id',inst.get('type_id',''))
            fasteners.append(classify_part(typ).value in ('BOLT','NUT'))
        if op.get('missing'):missing.append(op.get('operation_id'))
        if len(member_ids)>1:multi.append(member_ids)
        base=op.get('travel_mm',op.get('start_offset_mm',1))==0 or op is operations[0]
        if fasteners and not all(fasteners) and not base:
            general.append(op)
            direction=op.get('insertion_direction')
            if direction and sum(float(v)**2 for v in direction)>0:
                axis[str(tuple(-float(v) for v in direction))]+=1
    expected={str(x) for x in instance_map};counts=Counter(seen)
    steps=[p for p in folder.glob('*.step') if p.name.endswith('_ASSEMBLY.step')]
    return dict(sample=folder.name,assembly_files=[str(p) for p in steps],definitions=len(definitions),
        declared_solids=sum(d.get('solid_count',1)*d.get('quantity',0) for d in definitions),
        instances=len(instances),quantity_total=sum(d.get('quantity',0) for d in definitions),
        types=dict(Counter({typ:sum(d.get('quantity',0) for d in definitions if classify_part(d['part_id']).value==typ)
                            for typ in set(classify_part(d['part_id']).value for d in definitions)})),
        declared_family=card.get('family_id',manifest.get('family_id')),
        variant=card.get('variant',card.get('scope')),
        sequence_operations=len(operations),general_label_operations=len(general),
        potential_labeled_ranking_states=max(0,len(general)-1),removal_axis_counts=dict(axis),
        missing_sequence_members=missing,uncovered_instances=sorted(expected-set(seen)),
        duplicate_sequence_members={k:v for k,v in counts.items() if v>1},
        bundled_operations=len(multi),sequence_schema='sequence' if 'sequence' in sequence else 'operation_ids',
        sampled_geometry_claim=sequence.get('sampled_geometry_validated'),
        card=card,operations=operations,validation=read(folder/'labels/validation_report.json',{}),
        primary_files=[str(p) for p in [folder/'parameters.json',folder/'labels/assembly_manifest.json',folder/'labels/assembly_sequence.json',
            folder/'labels/dataset_card.json',folder/'labels/validation_report.json',folder/'metadata/operations.json'] if p.is_file()])


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    folders=sorted(p for p in INPUT.iterdir() if p.is_dir())
    records=[labels(p) for p in folders]
    (OUT/'labels.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    results=[];settings=AppSettings();started=time.perf_counter()
    for folder,record in zip(folders,records):
        begin=time.perf_counter();paths=[folder/(folder.name+'_ASSEMBLY.step')]+sorted((folder/'parts').glob('*.step'))
        hashes={str(p):sha(p) for p in paths}
        row={k:v for k,v in record.items() if k not in ('card','operations','validation')}
        try:
            scenes=[]
            for path in paths:
                scene=StepImporter().read(path,hashes[str(path)],'read-only-learning-audit/'+path.name)
                scene.original_name=path.name;scenes.append(scene)
            epsilon=settings.resolved_for_diagonal(scenes[0].bounds.diagonal)['geometry_epsilon_mm']
            grouped=GroupingService(settings.volume_relative_tolerance,epsilon).resolve(scenes[0],scenes[1:])
            grouped.assert_partition(b.id for b in scenes[0].bodies)
            general=[g for g in grouped.groups if not is_fastener(g)]
            row.update(import_ok=True,bodies=len(scenes[0].bodies),invalid_bodies=sum(not b.geometry_valid for b in scenes[0].bodies),
                groups=len(grouped.groups),general_groups=len(general),fastener_groups=len(grouped.groups)-len(general),
                unknown_type_groups=sum(g.part_type.value=='UNKNOWN' for g in grouped.groups),
                unmatched_bodies=len(grouped.unresolved_body_ids),ambiguous=grouped.ambiguous,
                unmatched_names=[g.display_name for g in grouped.groups if g.part_definition_id is None],
                group_types=dict(Counter(g.part_type.value for g in grouped.groups)),
                groups_data=[asdict(g) for g in grouped.groups],
                family_fingerprint=family_fingerprint(SimpleNamespace(atomic_bodies=scenes[0].bodies)),
                input_sha256=hashes[str(paths[0])],potential_raw_ranking_states=max(0,len(general)-2),
                size_mm=scenes[0].bounds.size)
        except Exception as exc:row.update(import_ok=False,error=str(exc),traceback=traceback.format_exc())
        row.update(input_files_unchanged=all(sha(Path(p))==h for p,h in hashes.items()),input_hashes=hashes,
            elapsed_sec=time.perf_counter()-begin)
        results.append(row)
        (OUT/'recognition.json').write_text(json.dumps(dict(scope='Read-only recognition and label analysis only',
            model_training_performed=False,contact_path_checks_performed=False,settings=asdict(settings),
            elapsed_sec=time.perf_counter()-started,samples=results),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:row.get(k) for k in ('sample','import_ok','bodies','groups','general_groups','fastener_groups',
            'unmatched_bodies','potential_raw_ranking_states','potential_labeled_ranking_states','elapsed_sec','error')},ensure_ascii=False),flush=True)
    return 0 if all(r.get('import_ok') and r['input_files_unchanged'] for r in results) else 1


if __name__=='__main__':raise SystemExit(main())
