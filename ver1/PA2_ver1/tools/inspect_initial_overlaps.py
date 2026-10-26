from __future__ import annotations

import argparse
import json
import multiprocessing
from pathlib import Path

from pa2.cli import _runtime
from pa2.cad.isolated import NativeCadSession


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-root",type=Path,required=True)
    p.add_argument("--project",required=True)
    p.add_argument("--planning",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--limit",type=int,default=6)
    args=p.parse_args()
    layout,_,_,imports=_runtime(args.data_root)
    r=imports.reopen(args.project)
    groups={g.id:g for g in r.snapshot.groups}
    d=json.loads(args.planning.read_text(encoding="utf-8"))["planning"]
    pairs=[]
    for result in d["paths"]:
        if result["reason_code"]=="INITIAL_OVERLAP":
            for other in result["obstacle_ids"]:
                pair=tuple(sorted((result["group_id"],other)))
                if pair not in pairs:
                    pairs.append(pair)
    rows=[]
    with NativeCadSession(r.snapshot.groups,r.assembly_scene.shapes,jobs_dir=layout.jobs) as worker:
        for a,b in pairs[:args.limit]:
            volume=worker.call("overlap",(a,b))
            row={"group_a":a,"group_b":b,"name_a":groups[a].display_name,"name_b":groups[b].display_name,
                 "common_volume_mm3":volume,"volume_a_mm3":groups[a].volume_mm3,"volume_b_mm3":groups[b].volume_mm3}
            rows.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
    args.output.write_text(json.dumps({"unique_pairs":len(pairs),"checked":rows},ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":
    multiprocessing.freeze_support()
    main()
