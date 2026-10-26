"""Read-only translated-solid witnesses for the cover/seal vertical question."""
from pathlib import Path
import json
import time
import sys
from dataclasses import asdict
from diagnose_unknowns import load_inputs
from diagnose_remaining import initialize, shape
from pa2.cad.path_check import _boolean
from pa2.cad.shapes import translated
from pa2.cad.sweep import bounds
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps


def measure(a, b):
    op = _boolean(BRepAlgoAPI_Common, a, b)
    result = op.Shape()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(result, props)
    volume = abs(props.Mass())
    return {'volume_mm3': volume, 'valid': BRepCheck_Analyzer(result).IsValid(),
            'bounds': asdict(bounds(result)) if volume > 1e-7 else None}


def main():
    report = json.loads(Path('runtime-data/native-validation/planning-binary-final.json').read_text(encoding='utf-8'))
    groups, files = load_inputs(report, Path('runtime-data/real-model'))
    initialize(groups, files)
    ids = {'cover': 'group-1584ffc67b-0001', 'seal': 'group-1d291d7b99-0001', 'body': 'group-3c66381834-0001'}
    output = {'description': 'Actual translated whole-solid intersections; diagnostic only. Input files are read-only.', 'groups': {}, 'pairs': []}
    for name, gid in ids.items():
        output['groups'][name] = {'id': gid, 'name': groups[gid].display_name, 'bounds': asdict(bounds(shape(gid)))}
    extra = '--after-cover' in sys.argv
    target = Path('runtime-data/native-validation/cover-seal-vertical-after-cover.json' if extra else 'runtime-data/native-validation/cover-seal-vertical-witnesses.json')
    pairs = [('cover', 'body', 1), ('seal', 'body', 1)] if extra else [('cover', 'seal', 1), ('cover', 'seal', -1), ('seal', 'cover', -1), ('seal', 'body', -1)]
    for moving_name, obstacle_name, sign in pairs:
        moving, obstacle = shape(ids[moving_name]), shape(ids[obstacle_name])
        relieved = _boolean(BRepAlgoAPI_Cut, obstacle, moving).Shape()
        pair = {'moving': moving_name, 'obstacle': obstacle_name, 'z_sign': sign,
                'relieved_valid': BRepCheck_Analyzer(relieved).IsValid(), 'samples': []}
        output['pairs'].append(pair)
        for distance in (0, .01, .1, .5, 1, 2, 5, 10):
            started = time.monotonic()
            positioned = translated(moving, (0, 0, sign * distance))
            row = {'distance_mm': distance, 'total_overlap': measure(positioned, obstacle),
                   'outside_initial_region': measure(positioned, relieved)}
            pair['samples'].append(row)
            target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
            print(moving_name, obstacle_name, sign, distance,
                  row['total_overlap']['volume_mm3'], row['outside_initial_region']['volume_mm3'],
                  round(time.monotonic()-started, 2), flush=True)


if __name__ == '__main__':
    main()
