"""Separate real/virtual native costs from zero-cost historical witness reuse."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from diagnose_unknowns import load_inputs


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    report=json.loads(args.report.read_text(encoding='utf-8')); run=report['planning']
    groups,_=load_inputs(report,args.root)
    costs=defaultdict(lambda: {'native_requests':0,'recorded_native_elapsed_sec':0.,'unknown_requests':0,'unknown_elapsed_sec':0.})
    scopes={}
    for scope,paths in [('actual',run['paths']),('virtual',run['metrics'].get('virtual_paths',[]))]:
        native=[q for q in paths if q['evidence']['evaluation_source']=='native']
        scopes[scope]={'records':len(paths),'native_requests':len(native),
            'recorded_native_elapsed_sec':sum(q['elapsed_sec'] for q in native),
            'unknown_native_requests':sum(q['decision']=='UNKNOWN' for q in native),
            'unknown_native_elapsed_sec':sum(q['elapsed_sec'] for q in native if q['decision']=='UNKNOWN'),
            'native_reasons':dict(Counter(q['reason_code'] for q in native))}
        for q in native:
            row=costs[q['group_id']]; row['native_requests']+=1; row['recorded_native_elapsed_sec']+=q['elapsed_sec']
            if q['decision']=='UNKNOWN':
                row['unknown_requests']+=1; row['unknown_elapsed_sec']+=q['elapsed_sec']
    output={'scopes':scopes,'parts':sorted([dict(group_id=gid,name=groups[gid].display_name,**row) for gid,row in costs.items()],
        key=lambda r:-r['recorded_native_elapsed_sec']),
        'note':'Sums unique recorded native results, including timeout elapsed. Witness reuse excluded. IPC/wait overhead is in the separate planner native_path_elapsed_sec metric.'}
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'scopes':scopes,'top_parts':output['parts'][:8]},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
