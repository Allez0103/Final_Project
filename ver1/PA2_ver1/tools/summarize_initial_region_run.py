"""Summarize a completed planning report without rerunning or changing CAD."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

from pa2.cad.path_check import state_key


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--markdown",type=Path)
    args=parser.parse_args()
    report=json.loads(args.report.read_text(encoding="utf-8"))
    run=report["planning"]; plan=run["plan"]
    db=sqlite3.connect((args.root/"database/pa2-dev.sqlite3").resolve().as_uri()+"?mode=ro",uri=True)
    try:
        names={identifier.split(":",1)[1]:name for identifier,name in db.execute(
            "select id,display_name from assembly_groups where snapshot_id=?",(plan["input_snapshot_id"],))}
    finally:
        db.close()
    remaining=set(plan["group_ids"])-set(run["removal_order"])
    key=state_key(remaining)
    unique={}
    for candidate in run["paths"]:
        if candidate["state_key"]==key:
            unique[(candidate["group_id"],tuple(candidate["direction"]),candidate["travel_mm"])]=candidate
    rows=[]
    for gid in sorted(remaining-{plan["base_group_id"]},key=lambda g:names.get(g,g)):
        candidates=[q for q in unique.values() if q["group_id"]==gid]
        decisions=Counter(q["decision"] for q in candidates)
        category="NOT_TESTED_IN_FINAL_STATE" if not candidates else "HAS_UNKNOWN" if decisions["UNKNOWN"] else "OBSERVED_DIRECTIONS_BLOCKED" if decisions["BLOCKED"]==len(candidates) else "OTHER"
        def diagnostic_codes(decision):
            codes=Counter()
            for q in candidates:
                if q['decision']!=decision:continue
                details=[detail['code'] for detail in q.get('evidence',{}).get('pair_diagnostics',[])
                         if detail.get('decision')==decision]
                codes.update(details or [q['reason_code']])
            return dict(codes)
        rows.append({"group_id":gid,"name":names.get(gid,gid),"category":category,
            "tested_directions":len(candidates),"decisions":dict(decisions),
            "reasons":dict(Counter(q["reason_code"] for q in candidates)),
            "related_parts":sorted({names.get(o,o) for q in candidates for o in q["obstacle_ids"]}),
            "blocked_by":sorted({names.get(o,o) for q in candidates if q["decision"]=="BLOCKED" for o in q["obstacle_ids"]}),
            "unknown_by":sorted({names.get(o,o) for q in candidates if q["decision"]=="UNKNOWN" for o in q["obstacle_ids"]}),
            "unknown_codes":diagnostic_codes('UNKNOWN'),"blocked_codes":diagnostic_codes('BLOCKED'),
            "candidates":candidates})
    output={"source_report":str(args.report),"status":run["status"],"reason":run["reason"],
        "metrics":run["metrics"],"removal_order_names":[names.get(g,g) for g in run["removal_order"]],
        "remaining_moving":len(rows),"final_state_key":key,
        "remaining_categories":dict(Counter(row["category"] for row in rows)),
        "coverage_note":"Only candidates tested in the retained final state are counted. Untested parts/directions are not diagnosed as blocked. A budget-limited result is not a maximum achievable sequence.",
        "remaining":rows}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    if args.markdown:
        clean=lambda value:str(value).replace('|','\\|').replace('\n',' ')
        labels={'INPUT_GEOMETRY_INVALID':'입력 정밀 검사/보정 한계',
                'INITIAL_REGION_CUT_INVALID':'초기 영역 차감 형상 무효','SWEEP_UNRESOLVED':'곡면 이동 영역 미해결',
                'OVERLAP_REINCREASE':'겹침 부피 재증가','DECREASE_TAIL_BLOCKED':'겹침 해소 후 경로 충돌',
                'DECREASE_TAIL_UNKNOWN':'겹침 해소 후 연속 경로 미판정','DECREASE_BOOLEAN_FAILED':'이동 위치 교차 계산 실패',
                'DECREASE_SAMPLE_BUDGET':'검사 위치 수 제한','TIME_BUDGET_EXCEEDED':'시간 제한',
                'CANDIDATE_TIME_BUDGET':'후보 시간 제한','PATH_BLOCKED':'이동 경로 충돌','PATH_UNKNOWN':'경로 미판정'}
        lines=['# 수정 후 잔여 부품별 진단','',
            f"생성 단계 {run['metrics']['completed_groups']}/{run['metrics']['total_moving_groups']}. 원본 결과: `{args.report.name}`.",'',
            '아래는 확보한 최장 순서 끝 상태에서 검사한 **유한 직선 방향**의 결과입니다. 모든 가능한 이동 방법의 불가능 판정은 아닙니다. 차단에는 겹침 부피 재증가와 경로 충돌이 포함됩니다. 미판정은 충돌 확정이 아니며, 다른 상대에서 차단 근거가 확인되면 해당 방향의 최종 판정은 BLOCKED입니다.','',
            '| 부품 | 방향 수 | 차단 | 미판정 | 차단 상대(방향별 상이) | 차단 근거 | 미판정 근거 |',
            '|---|---:|---:|---:|---|---|---|']
        for row in rows:
            reasons=', '.join(labels.get(c,c) for c in row['unknown_codes']) or ('미검사' if not row['candidates'] else '—')
            lines.append('| '+' | '.join(map(clean,[row['name'],row['tested_directions'],row['decisions'].get('BLOCKED',0),
                row['decisions'].get('UNKNOWN',0),', '.join(row['blocked_by']) or '—',
                ', '.join(labels.get(c,c) for c in row['blocked_codes']) or '—',reasons]))+' |')
        lines.extend(['','부품별 방향 벡터·거리·상대 ID·보정 수치는 요약 JSON의 `remaining[].candidates`에 보관합니다.'])
        args.markdown.parent.mkdir(parents=True,exist_ok=True)
        args.markdown.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k!="remaining"},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
