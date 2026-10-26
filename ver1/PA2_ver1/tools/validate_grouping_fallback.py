"""Read cached real CAD, run grouping only, and compare the saved v16 snapshot.

Does not import a new project, build contacts, generate a plan, or render video.
Reference STEP files and the existing database are read-only.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from diagnose_unknowns import load_inputs
from pa2.cad.brep_cache import load_scene
from pa2.cad.grouping import GroupingService
from pa2.settings.config import AppSettings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--parts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    report = json.loads(args.report.read_text(encoding='utf-8'))
    before, _ = load_inputs(report, args.root)
    references = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in args.parts.iterdir() if path.suffix.lower() in ('.stp', '.step')}
    names = {digest: path.name for path, digest in references.items()}
    scenes = []
    for directory in sorted((args.root / 'cache/shape').iterdir()):
        manifest = json.loads((directory / 'scene.json').read_text(encoding='utf-8'))
        scene = load_scene(directory, Path(manifest['source_path']))
        scene.original_name = names.get(scene.source_hash, 'assembly.stp')
        scenes.append(scene)
    assembly = next(scene for scene in scenes if scene.source_hash not in names)
    parts = [scene for scene in scenes if scene.source_hash in names]
    if len(parts) != len(references):
        raise RuntimeError('Not every reference part has a cached scene')
    settings = AppSettings(**report['settings'])
    epsilon = settings.resolved_for_diagonal(assembly.bounds.diagonal)['geometry_epsilon_mm']
    service = GroupingService(settings.volume_relative_tolerance, epsilon)
    result = service.resolve(assembly, parts)
    after = {group.id: group for group in result.groups}
    air = [group for group in result.groups if group.display_name == 'AIR-BENT0A']
    expected_bodies = {'body-3048cab7cc1d-000000', 'body-3048cab7cc1d-000001'}
    if len(air) != 1 or set(air[0].body_ids) != expected_bodies:
        raise RuntimeError('AIR-BENT did not match the expected two assembly bodies')
    replaced = {'group-' + body_id for body_id in expected_bodies}
    # SQLite JSON restores centroids as lists; in-memory grouping uses tuples.
    def canonical(group):
        return json.loads(json.dumps(asdict(group)))
    changed = [gid for gid in before.keys() - replaced
               if gid not in after or canonical(before[gid]) != canonical(after[gid])]
    if changed:
        raise RuntimeError(f'Unexpected changes to other groups: {changed}')
    if set(after) != (set(before) - replaced) | {air[0].id}:
        raise RuntimeError('Unexpected added or removed groups')
    if len(result.fallback_matches) != 1 or result.ambiguous:
        raise RuntimeError('Unexpected fallback candidates')
    result.assert_partition(body.id for body in assembly.bodies)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest in references.items()):
        raise RuntimeError('Reference file hash changed')
    output = {
        'ok': True, 'scope': 'cached-real-CAD grouping only; no project overwrite, contacts, planning or video',
        'policy': service.VERSION, 'part_files': len(parts), 'atomic_bodies': len(assembly.bodies),
        'strict_relative_tolerance': service.volume_relative_tolerance,
        'strict_position_tolerance_mm': service.position_tolerance_mm,
        'fallback_matches': result.fallback_matches, 'air_bent': asdict(air[0]),
        'groups_before': len(before), 'groups_after': len(after),
        'unmatched_bodies_before': sum(len(g.body_ids) for g in before.values() if g.part_definition_id is None),
        'unmatched_bodies_after': len(result.unresolved_body_ids),
        'other_groups_unchanged': len(before) - len(replaced), 'ambiguous': result.ambiguous,
        'reference_files_unchanged': True, 'collision_geometry_epsilon_mm_unchanged': epsilon,
        'settings_unchanged': asdict(settings) == report['settings'],
        'elapsed_sec': time.perf_counter() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
