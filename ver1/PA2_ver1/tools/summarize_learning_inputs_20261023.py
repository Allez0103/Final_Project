"""Summarize read-only audit facts; no database, training or evaluation calls."""
import ast,hashlib,json,math
from collections import Counter
from pathlib import Path
from pa2.settings.config import AppSettings

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runtime-data/learning-input-audit-20261023'


def main():
    raw=json.loads((OUT/'recognition.json').read_text(encoding='utf-8'))
    labels=json.loads((OUT/'labels.json').read_text(encoding='utf-8'))
    samples=raw['samples'];axes=Counter();arbitrary=0;precedence_errors=[]
    axis_vectors=[(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]
    axis_names=['+X','-X','+Y','-Y','+Z','-Z']
    for row in labels:
        for key,count in row['removal_axis_counts'].items():
            v=ast.literal_eval(key);length=math.sqrt(sum(x*x for x in v))
            dots=[sum(a*b for a,b in zip(v,axis))/length for axis in axis_vectors]
            k=max(range(6),key=dots.__getitem__)
            if dots[k]>=math.cos(math.radians(1)):axes[axis_names[k]]+=count
            else:arbitrary+=count
        operations=row['operations'];positions={o.get('operation_id',o.get('unit_id')):i for i,o in enumerate(operations)}
        for i,op in enumerate(operations):
            for predecessor in op.get('predecessors',op.get('requires',[])):
                if predecessor not in positions or positions[predecessor]>=i:
                    precedence_errors.append(dict(sample=row['sample'],op=op.get('operation_id',op.get('unit_id')),predecessor=predecessor))
    settings=AppSettings()
    result=dict(scope='Input suitability, recognition and label consistency only; not training/model evaluation or collision validation',
        samples=len(samples),import_ok=sum(r['import_ok'] for r in samples),
        assembly_step_files=len(samples),part_step_files=sum(r['definitions'] for r in labels),
        total_solid_bodies=sum(r['bodies'] for r in samples),groups=sum(r['groups'] for r in samples),
        general_groups=sum(r['general_groups'] for r in samples),fastener_groups=sum(r['fastener_groups'] for r in samples),
        unmatched_bodies=sum(r['unmatched_bodies'] for r in samples),invalid_bodies=sum(r['invalid_bodies'] for r in samples),
        ambiguous_samples=sum(bool(r['ambiguous']) for r in samples),unknown_type_groups=sum(r['unknown_type_groups'] for r in samples),
        unique_program_geometric_fingerprints=len({r['family_fingerprint'] for r in samples}),
        same_declared_lineage_s11_s45=sum(r['declared_family']=='KD1_HVJB_shared_synthetic_design_lineage' for r in labels),
        potential_raw_ranking_states=sum(r['potential_raw_ranking_states'] for r in samples),
        potential_labeled_ranking_states=sum(r['potential_labeled_ranking_states'] for r in labels),
        label_operations=sum(r['sequence_operations'] for r in labels),
        general_labeled_moves=sum(r['general_label_operations'] for r in labels),direction_axis_counts=dict(axes),
        non_six_axis_moves=arbitrary,precedence_errors=precedence_errors,
        missing_member_samples=[r['sample'] for r in labels if r['missing_sequence_members'] or r['uncovered_instances'] or r['duplicate_sequence_members']],
        label_schemas=dict(Counter(r['sequence_schema'] for r in labels)),
        bundled_label_operations=sum(r['bundled_operations'] for r in labels),
        files_unchanged=all(r['input_files_unchanged'] for r in samples),
        verified_cad_files=sum(len(r['input_hashes']) for r in samples),elapsed_sec=raw['elapsed_sec'],
        thresholds=dict(families=settings.training_min_families,states=settings.training_min_states,
            direction_samples=settings.direction_min_samples,axes=settings.direction_min_axes,per_axis=settings.direction_min_per_axis),
        model_training_performed=False,models_evaluated=False,projects_created=False,
        program_modified=False,exe_sha256=hashlib.sha256((ROOT/'PA2.exe').read_bytes()).hexdigest())
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    text=f'''# learning 폴더 학습 입력 적합성 분석

2026-10-23. 대상: 바탕화면 data_example/learning. 원본·프로그램·EXE·ZIP·사용자 DB를 수정하지 않았다. 동봉 생성/검증 스크립트를 실행하지 않았고, 학습·모델 평가·접촉/간섭·경로 검사도 실행하지 않았다. 현재 STEP importer와 자동 그룹화 및 파일명 분류를 직접 적용한 입력 분석이다.

## 결론

학습 흐름의 기능 시험 및 합성 순서/방향 추천 실험용으로는 사용할 수 있다. 그러나 현 상태를 실용 모델의 성능 검증이나 자동 적용을 위한 충분한 독립 실데이터로 보기는 어렵다. CAD와 예시 라벨을 PA2의 확정 프로젝트/수집 형식으로 연결해야 하며, 현재 기본 공통 학습 시작 기준에도 미달한다.

## 실측 입력 상태

- S01~S45, 완제품 STEP {result['assembly_step_files']}개와 parts/ 정의 STEP {result['part_step_files']}개를 읽었다. OPEN, parts_positioned, source_legacy 및 중복 보관본은 별도 학습 프로젝트로 세지 않았다.
- {result['total_solid_bodies']:,}솔리드 → {result['groups']:,}그룹. 일반 {result['general_groups']:,}, 볼트/너트 {result['fastener_groups']:,}. 45/45 읽기·그룹화 성공, 미매칭 {result['unmatched_bodies']}, 무효 바디 {result['invalid_bodies']}, 모호한 매칭 샘플 {result['ambiguous_samples']}.
- CAD {result['verified_cad_files']}개 SHA-256 전후 동일. 인식 분석 약 {result['elapsed_sec']:.2f}초. 이는 순서 생성/학습 소요 시간이 아니다.
- UNKNOWN 종류 {result['unknown_type_groups']}개는 매칭 실패가 아니라 기존 분류 enum/별칭으로 세분하지 않은 일반 부품이다. 새 이름 CONTACTOR_ASSEMBLY, HV_PORT_ASSEMBLY, LV_PORT_ASSEMBLY 등도 포함된다. 치수·위치 특징은 쓸 수 있으나 기능별 종류 특징은 덜 구체적이다.

## 데이터 수와 현재 기본 기준

| 항목 | 이번 입력 | 프로그램 기본 기준/해석 |
|---|---:|---|
| 서로 다른 기하 중복 억제 키 | {result['unique_program_geometric_fingerprints']} | 최소 {settings.training_min_families}; 통계적으로 독립인 설계 45종이라는 뜻은 아님 |
| 원시 그룹을 모두 확정할 경우 잠재 순서 상태 | {result['potential_raw_ranking_states']} | 최소 {settings.training_min_states}; {settings.training_min_states-result['potential_raw_ranking_states']}개 부족 |
| 동봉 예시의 작업 단위를 유지한 잠재 순서 상태 | {result['potential_labeled_ranking_states']} | 최소 {settings.training_min_states}; 현재 자동 그룹 단위와 차이가 있음 |
| 동봉 일반 부품 방향 예시 | {result['general_labeled_moves']} | 6축 허용 예시 {sum(axes.values())}개 + 임의 각도 {arbitrary}개 |

위 수치는 잠재 입력 규모이지 현재 DB에 저장된 학습 사례 수가 아니다. 원시 순서 상태는 기준 부품 1개, 볼트/너트 제외, 매 샘플 완전 순서 1개, 일반 부품 후보가 2개 이상인 시점만 세어 일반 그룹 수 - 2를 합산한 값이다. 확정 누락/부분 순서/프로젝트 중복은 수집 결과를 줄일 수 있다. 반복 확정이나 볼트 개수로 상태 수를 부풀리지 않는다.

## 방향 다양성

분해 방향 기준(동봉 삽입 방향의 반대): {dict(axes)}. +Z {axes['+Z']}/{result['general_labeled_moves']}개, 약 {axes['+Z']/result['general_labeled_moves']*100:.1f}%. 방향 선호 최소 100사례 및 최소 2축 각각 10사례는 동봉 라벨 숫자상 충족할 수 있지만, 공통 30계열/1,000상태 기준은 별도이며 실제 DB 매핑·수집 후 다시 확인해야 한다. -Z는 {axes['-Z']}개로 부족하고 비6축 {arbitrary}개는 현재 방향 모델이 허위로 6축에 반올림하지 않고 제외한다.

## 계열 누수와 평가 한계

- S11~S45 {result['same_declared_lineage_s11_s45']}개는 dataset_card/manifest/split_policy에서 같은 KD1_HVJB_shared_synthetic_design_lineage로 표시되어 있다. S01~S10에도 앞 샘플과 공유한 설계 계보가 명시되어 있다.
- 현재 family_fingerprint는 바디 체적·경계 크기·상대 중심 거리로 단순한 중복을 억제한다. 이번 45개가 서로 다른 키여도 동일 설계의 치수/배치 변형 관계는 식별하지 못한다. 현재 학습 모듈은 동봉 split_policy.json을 자동으로 읽지 않는다.
- 이 키만으로 유사 변형을 학습/평가 양쪽에 나누면 새 설계에 대한 성능을 과대평가할 수 있다. 같은 설계 계보는 같은 분할에 묶고, 별도 구조나 독립 실물 조립체를 평가용으로 확보해야 한다. 임의로 '45개 독립 계열'로 간주하면 안 된다.

## 라벨 형식과 연결 과제

- 예시 작업 {result['label_operations']:,}개. S01~S10은 labels/assembly_sequence.json의 sequence 형식, S11~S45는 operation_ids와 metadata/operations.json을 함께 쓰는 형식이다.
- 라벨 구성원 누락/중복 샘플: {result['missing_member_samples']}. 선후관계 참조/순서 오류: {len(precedence_errors)}건. 단순 ID·커버리지 검증이며 물리 가능성 증명은 아니다.
- S01~S10에는 여러 원시 부품을 한 작업으로 묶은 라벨 {result['bundled_label_operations']}개가 있다. 현재 자동 그룹은 이 구매품/작업 묶음을 전부 자동 재현하지 않으므로, 원시 그룹 979상태와 작업 묶음 813상태는 서로 다른 단위다. 묶음 내부 순서를 임의로 정답처럼 만들면 안 된다.
- 현재 ImportService는 STEP과 개별 부품 STEP을 읽고, 학습은 프로그램에서 생성·수정·확정한 순서를 수집한다. 동봉 JSON/CSV 예시 순서·방향·접촉·negative_order_examples는 자동 입력되지 않는다. 파일을 둔 것만으로 DB 학습 데이터가 생성되지는 않는다.
- 예시를 쓰려면 작업 ID/배치 ID를 PA2 그룹 ID와 대응시키고, 기준 부품을 제외한 완전 순서·분해 방향·단위 묶음을 검토해 확정 데이터로 연결해야 한다. 수동생성 기본값을 확인 없이 확정하면 예시 정답 대신 목록 순서와 +Z를 학습하게 된다.
- 동봉 검증 보고서는 표본 위치 간섭 검사 결과이며 PA2의 연속 경로 검증과 다르다. 예시 선호로는 사용할 수 있지만 전부 물리 PASS/최적 순서로 취급하면 안 된다. 자동 승격 평가에 필요한 PA2 정책의 저장 접촉 그래프/원본 캐시도 파일 JSON만으로 대체되지 않는다.

## 권장 진행

1. 현재 데이터는 제한된 합성 기능 시험/초기 실험용으로 사용한다. 실제 학습 실행은 별도 승인 후 진행한다.
2. 먼저 두 라벨 형식을 공통 포맷으로 읽고 PA2 그룹과 대응시키는 준비가 필요하다. 데이터 원본 수정 없이 별도 변환/시험 DB를 사용할 수 있다.
3. 기본 최소 상태를 맞추려면 구조적으로 다른 일반 부품 사례를 보강한다. 원시 기준은 21상태 부족하지만 단순 숫자 충족보다 설계 계보 다양성과 독립 평가 데이터가 더 중요하다. 생산 설정의 기준을 임의로 낮추지 않는다.
4. +Z 외 방향을 보강하고 동일 계보끼리 평가에 섞이지 않게 한다. 기능 시험 성공, 합성 데이터의 점수, 실제 조립 성능/자동 적용 적합성은 구분한다.

근거: runtime-data/learning-input-audit-20261023/recognition.json, labels.json, summary.json. 현재 실행 파일 SHA-256: {result['exe_sha256']} (v26과 동일).
'''
    path=ROOT/'docs/LEARNING_INPUT_SUITABILITY_20261023.md';path.write_text(text,encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));print(str(path))


if __name__=='__main__':main()
