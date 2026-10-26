"""Read-only STEP/classification/grouping audit. Never contacts/plans/trains.

Input CAD and labels are data, not executable generation scripts. Only the
requested output report is written, inside the development workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from pa2.cad.grouping import GroupingService
from pa2.cad.importer import StepImporter
from pa2.domain.classification import classify_part
from pa2.settings.config import AppSettings

PROTECTED = ('cad/path_check.py', 'cad/contacts.py', 'cad/sweep.py', 'cad/prepare.py',
             'cad/native_worker.py', 'cad/boolean_options.py', 'cad/directions.py',
             'planning/engine.py', 'planning/two_stage.py', 'planning/fastener_direction.py',
             'planning/manual.py', 'settings/config.py', 'learning/pipeline.py',
             'learning/models.py', 'learning/collection.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(folder, assembly_file):
    paths = [assembly_file]+sorted(p for p in (folder/'parts').iterdir()
                                   if p.suffix.lower() in ('.stp', '.step'))
    before = {str(p): sha(p) for p in paths}
    scenes = []; started = time.perf_counter()
    for path in paths:
        scene = StepImporter().read(path, before[str(path)], 'readonly-audit/'+path.name)
        scene.original_name = path.name; scenes.append(scene)
    settings = AppSettings()
    epsilon = settings.resolved_for_diagonal(scenes[0].bounds.diagonal)['geometry_epsilon_mm']
    grouping = GroupingService(settings.volume_relative_tolerance, epsilon).resolve(scenes[0], scenes[1:])
    grouping.assert_partition(b.id for b in scenes[0].bodies)
    result = dict(sample=folder.name, input_assembly=str(assembly_file),
        body_count=len(scenes[0].bodies), group_count=len(grouping.groups),
        invalid_bodies=sum(not b.geometry_valid for b in scenes[0].bodies),
        part_files=len(paths)-1, matched_groups=sum(g.part_definition_id is not None for g in grouping.groups),
        unmatched_bodies=len(grouping.unresolved_body_ids), ambiguous=grouping.ambiguous,
        fallback_matches=grouping.fallback_matches, rotation_matches=getattr(grouping, 'rotation_matches', []),
        definition_types=dict(Counter(classify_part(p.name).value for p in paths[1:])),
        group_types=dict(Counter(g.part_type.value for g in grouping.groups)),
        groups=[asdict(g) for g in grouping.groups],
        input_hashes=before, source_files_unchanged=all(sha(Path(p)) == h for p, h in before.items()),
        elapsed_sec=time.perf_counter()-started)
    manifest = folder/'labels/assembly_manifest.json'
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding='utf-8'))
        result['expected_bolt_instances'] = sum(d['quantity'] for d in data['definitions']
                                               if d['part_id'].startswith('BOLT_'))
        result['unknown_definitions'] = [p.name for p in paths[1:] if classify_part(p.name).value == 'UNKNOWN']
    print(json.dumps({k: v for k, v in result.items() if k not in
        ('groups', 'input_hashes', 'ambiguous', 'fallback_matches', 'rotation_matches', 'unknown_definitions')}, ensure_ascii=False), flush=True)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    folders=[]
    for top in sorted(p for p in args.data_root.iterdir() if p.is_dir()):
        folder=top if (top/'parts').is_dir() else next((p for p in top.iterdir()
            if p.is_dir() and (p/'parts').is_dir()), None)
        if folder:folders.append(folder)
    rows=[audit(folder,folder/(folder.name+'_ASSEMBLY.step')) for folder in folders]
    reference=audit(args.reference_root, next(p for p in args.reference_root.iterdir()
        if p.suffix.lower() in ('.step','.stp')))
    import pa2
    package=Path(pa2.__file__).resolve().parent
    result=dict(scope='STEP recognition only; no contacts, plans, training, model evaluation or video',
        loaded_source=str(package), policy=GroupingService.VERSION,
        settings=asdict(AppSettings()), protected_source_hashes={p:sha(package/p) for p in PROTECTED},
        samples=rows, reference=reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(r['source_files_unchanged'] for r in rows+[reference]) else 1


if __name__=='__main__':raise SystemExit(main())
