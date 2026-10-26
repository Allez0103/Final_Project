"""Compare the measured single-search run with the preserved v14 baseline."""
import argparse, json
from pathlib import Path
from collections import Counter
from diagnose_unknowns import load_inputs
from pa2.cad.path_check import state_key


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--markdown',type=Path,required=True); args=parser.parse_args()
    raw=json.loads(args.report.read_text(encoding='utf-8')); run=raw['planning']; m=run['metrics']
    old=json.loads((args.report.parent/'planning-v14-cache-final.json').read_text(encoding='utf-8')); om=old['planning']['metrics']
    groups,_=load_inputs(raw,args.root); name=lambda gid:groups[gid].display_name
    old_groups,_=load_inputs(old,args.root.parent/'end-to-end-v14-cache-final')
    same_input=groups.keys()==old_groups.keys() and all((g.body_ids,g.bounds,g.part_type)==(old_groups[gid].body_ids,old_groups[gid].bounds,old_groups[gid].part_type) for gid,g in groups.items())
    general_count=sum(g.part_type.value not in ('BOLT','NUT') for g in groups.values())-1
    unresolved=[]
    for gid in m['unresolved_general_ids']:
        paths=[p for p in run['paths'] if p['group_id']==gid and p['decision'] in ('BLOCKED','UNKNOWN')]
        final_state=paths[-1]['state_key'] if paths else None
        latest=[p for p in paths if p['state_key']==final_state]
        codes=Counter(d['code'] for p in paths for d in p['evidence'].get('pair_diagnostics',[]) if 'code' in d)
        unresolved.append({'group_id':gid,'name':name(gid),'last_test_state':final_state,
            'last_state_decisions':dict(Counter(p['decision'] for p in latest)),
            'last_state_paths':latest,
            'reason_counts':dict(Counter(p['reason_code'] for p in paths)),'pair_codes':dict(codes),
            'obstacles':sorted({name(o) for p in paths for o in p['obstacle_ids']}),
            'native_errors':sorted({p['evidence']['native_error'] for p in paths if p['evidence'].get('native_error')})})
    order=run['removal_order']; positions={gid:i for i,gid in enumerate(order)}; inserted=[]
    exceptions=set(m['collision_exception_ids']); fasteners=set(m['fastener_attachments'])
    remaining=set(groups)-fasteners-exceptions; steps={s['group_id']:s for s in run['plan']['steps']}; state_audit=[]
    for gid in order:
        if gid in fasteners or gid in exceptions:continue
        step=steps[gid]
        matches=[p for p in run['paths'] if p['group_id']==gid and p['state_key']==state_key(remaining)
                 and max(abs(a-b) for a,b in zip(p['direction'],step['removal_direction']))<1e-9
                 and abs(p['travel_mm']-step['travel_mm'])<1e-8
                 and (p['reason_code']=='DRAFT_UNRESOLVED' if step['geometry_status']=='DRAFT_UNRESOLVED' else p['decision']=='PASS')]
        assert matches,('adopted general state mismatch',name(gid))
        state_audit.append({'name':name(gid),'decision':matches[-1]['decision'],'state_key':matches[-1]['state_key'],'elapsed_sec':matches[-1]['elapsed_sec']})
        remaining.remove(gid)
    assert remaining=={run['plan']['base_group_id']}
    for gid,relation in m['fastener_attachments'].items():
        owners=[t for t in relation['targets'] if t in positions]
        if owners:assert positions[gid]<min(positions[t] for t in owners),(gid,owners)
        assigned=[p for p in run['paths'] if p['group_id']==gid and p['reason_code']=='FASTENER_AXIS_ASSIGNED']
        assert len(assigned)==1 and assigned[0]['evidence']['path_check_skipped']
        inserted.append({'name':name(gid),'targets':[name(t) for t in relation['targets']],
                         'inserted_before':name(assigned[0]['evidence']['target_group_id']),'method':relation['method']})
    assert len(order)==len(set(order))==len(groups)-1
    assert not m.get('virtual_candidate_records')
    normal_calls=[p for p in run['paths'] if p['evidence'].get('evaluation_source')=='native']
    assert all(groups[p['group_id']].part_type.value not in ('BOLT','NUT') for p in normal_calls)
    rows=[('입력·그룹화·접촉 준비 (초)',old['contact_elapsed_sec'],raw['contact_elapsed_sec']),
          ('순서 생성 시간 (초)',om['elapsed_sec'],m['elapsed_sec']),
          ('초안 단계 수',om['completed_groups'],m['completed_groups']),
          ('후보 기록 수',om['tested_candidates']+om.get('virtual_candidate_records',0),m['tested_candidates']+m.get('virtual_candidate_records',0)),
          ('신규 CAD 경로 요청',om['native_path_calls'],m['native_path_calls']),
          ('부품 쌍 계산',om['pair_calculations'],m['pair_calculations']),
          ('BREP Common 호출',om['brep_common_calls'],m['brep_common_calls']),
          ('일반 부품 경로 통과 단계',om['verified_path_steps'],m['verified_path_steps']),
          ('체결부 배치 단계',om['fastener_assigned_steps'],m['fastener_assigned_steps']),
          ('사용자 예외 단계',om['collision_exception_steps'],m['collision_exception_steps']),
          ('미해결 일반 부품',om['unresolved_general_steps'],m['unresolved_general_steps'])]
    old_video_path=args.report.parent/'video-v14-final/video-validation.json'
    new_video_path=args.report.parent/'video-v16-final/video-validation.json'
    if old_video_path.exists() and new_video_path.exists():
        old_video=json.loads(old_video_path.read_text(encoding='utf-8'))
        new_video=json.loads(new_video_path.read_text(encoding='utf-8'))
        rows.extend([('기본 영상 생성 시간 (초)',old_video['render_elapsed_sec'],new_video['render_elapsed_sec']),
                     ('기본 영상 재생 길이 (초)',old_video['duration_sec'],new_video['duration_sec'])])
    output={'ok':True,'comparison':[{'metric':k,'v14':a,'v16':b} for k,a,b in rows],
            'planning_time_reduction_percent':100*(1-m['elapsed_sec']/om['elapsed_sec']),
            'native_request_reduction_percent':100*(1-m['native_path_calls']/om['native_path_calls']),
            'unresolved':unresolved,'fastener_insertion_audit':inserted,'general_moving_parts':general_count,
            'general_state_audit':state_audit,
            'draft_complete':m['draft_complete'],'path_complete':m['path_complete'],
            'same_input_groups':same_input,
            'settings_changes':{k:{'v14':old['settings'][k],'v16':v} for k,v in raw['settings'].items() if old['settings'].get(k)!=v}}
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# v16 전체 실행 및 영상 검증','',
        '볼트·너트를 제외한 일반 부품을 한 번 탐색한 뒤 체결부를 삽입했다. LV CONT, HVSC 2800 #1/#2를 예외로 지정했다.',
        '','| 항목 | 이전 v14 | 이번 v16 |','|---|---:|---:|']
    for key,a,b in rows:lines.append(f'| {key} | {a:.2f} | {b:.2f} |' if isinstance(a,float) else f'| {key} | {a} | {b} |')
    lines+=['',f"순서 생성 시간 감소 {output['planning_time_reduction_percent']:.1f}%, 신규 경로 요청 감소 {output['native_request_reduction_percent']:.1f}%.",
        '',f"입력 그룹·구성 바디·경계·부품 분류 일치={same_input}. 후보 {m['tested_candidates']}건 중 차단 근거 재사용 {m.get('blocked_witness_cache_hits',0)}건이며, 동일 상태의 부품 판정 재사용은 {m.get('group_evaluation_cache_hits',0)}회다.",
        '', '이전 v14와 후보 제한(180→240초), 예외 부품 수(1→3), 탐색 구조가 다르다. 모두 새 입력 캐시 실행이며, 단일 실행 중 UI 시험·EXE 빌드 부하가 포함되므로 동일 조건의 반복 성능시험은 아니다.',
        '', '영상 생성 시간은 영상 길이·프레임 수도 함께 달라진 단일 실행 수치다.',
        '',f"전체 초안 {m['completed_groups']}/{m['total_moving_groups']}단계. 모든 경로 검증 완료={m['path_complete']}. 일반 부품의 경로 통과는 전체 체결부를 제외한 상태의 결과이며, 체결부는 상세 경로 검사 없이 축방향 배치한다.",
        '', '부품 쌍/Common 호출 수는 결과를 반환한 네이티브 요청의 집계다. 시간 초과로 종료한 요청의 부분 호출 수는 반환되지 않을 수 있으므로 신규 요청 수·시간 초과 수와 함께 해석한다.',
        '', '## 막힌 부품과 원인','', '| 부품 | 마지막 검사 상태의 판정 | 상세 원인 | 상대 부품 |','|---|---|---|---|']
    for row in unresolved:lines.append(f"| {row['name']} | {row['last_state_decisions']} | {row['pair_codes']} {row['native_errors']} | {', '.join(row['obstacles'])} |")
    lines+=['','위 판정은 기록된 직선 방향과 잔여 상태에 대한 결과다. 미해결 단계를 보충한 뒤 다시 검사한 결과나 모든 분해 방법의 불가능 증명이 아니다.',
        '',f"채택된 일반 부품 {len(state_audit)}개의 잔여 상태·방향·거리와 검사 기록을 대조했다. 두 릴레이는 이번 자동 순서에서 경로 통과 단계로 채택됐다.",
        '', '## 체결부 삽입','',f"{len(inserted)}개 체결부를 중복 없이 삽입했다. 연결된 이동 부품들 중 첫 제거 부품보다 먼저 배치한 것을 감사했다. 연결 대상이 고정 부품뿐이거나 접촉 근거가 없는 체결부는 말미에 배치하고 JSON에 근거를 보존했다.",
        '', '## 영상 및 UI 검증','', '영상 생성·수동 편집 후 재검토·플레이어·EXE 검증 수치는 아래 후속 검증 결과를 함께 확인한다.']
    for file in ('video-v16-final/video-validation.json','ui-review-v16-final.json'):
        path=args.report.parent/file
        if path.exists():
            value=json.loads(path.read_text(encoding='utf-8'))
            lines+=['',f'### {file}','',f"성공={value.get('ok')}, 단계={value.get('steps')}, 생성 시간={value.get('render_elapsed_sec',0):.2f}초, 영상={value.get('path')}, CAD 재검사={value.get('cad_revalidation_calls')}회."]
            if 'fullscreen_escape' in value:lines+=['',f"실제 재검토 버튼 렌더={value.get('review_button_actual_render')}, 미리보기 디코딩 프레임={value.get('preview_frames')}, 배속={value.get('playback_rate')}, Esc 전체화면 해제={value.get('fullscreen_escape')}, 전체 디코딩 프레임={value.get('decoded_frame_count')}."]
    lines+=['','## 배포·원본 보존','']
    for file in ('packaged-source-check-v16-final.json','reference-integrity-v16.json','native-smoke-v16-final.json','gui-reopen-v16-final.json'):
        path=args.report.parent/file
        if path.exists():
            evidence=json.loads(path.read_text(encoding='utf-8'))
            lines.append(f"- {file}: 성공={evidence.get('ok')}."+(f" EXE SHA-256={evidence['executable_sha256']}" if 'executable_sha256' in evidence else ''))
    lines+=['','회귀시험: tests-v16-delivery.log의 201개 통과, 외부 실제 STEP 시험 1개는 별도 전체 실행으로 수행했다. 설치 개발환경이 없는 별도 PC의 검증은 이번 실행 범위에 포함하지 않았다.',
            '', '## 검증 도구 보완 기록', '',
            '첫 영상 검증은 감시 대상 클래스의 진입점 이름 오류로 렌더 시작 전에 종료했다. 실제 IsolatedCadWorker.call을 감시하도록 수정한 뒤 기본 영상을 완성했다. 예비 EXE 시험에서는 다중선택이 유지돼 방향 적용이 생략된 것을 발견했다. 단일선택을 명시하고 최적화된 EXE에서 생략되는 assert 대신 명시적 조건 검사를 사용했으며 Qt Flow 열거형 접근도 바로잡았다. 예비 ui-review-v16.json은 순서 변경만 확인한 기록이며, 최종 판단은 ui-review-v16-final.json을 사용한다.',
            '', '최종 GUI 검증은 실제 재검토 버튼을 사용하고 진행률 중간값을 수집했다. QWidget 캡처의 native OpenGL 영역이 검게 찍힐 수 있어 ui-review-v16-final-scene.png에 VTK 렌더 버퍼를 따로 저장하고 형상을 확인했다. Qt 위젯 HWND와 VTK의 HWND도 일치함을 확인했다.',
            '', '실행: open_validation_v16.bat. 사용자 편집·재검토·영상 생성은 간섭 검사를 생략하며 형식 검사만 유지한다.']
    args.markdown.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'ok':True,'planning_time_reduction_percent':output['planning_time_reduction_percent'],'unresolved':len(unresolved)},ensure_ascii=False))


if __name__=='__main__':main()
