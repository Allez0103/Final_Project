# 프로젝트 저장·관리 중심 ERD — 발표용

현재 31개 테이블 중 프로젝트 저장·관리를 설명하는 핵심 6개만 남긴 요약이다. 실제 외래키가 선언된 주요 관계만 연결했고, 테이블별 필드를 3~4개로 줄였다.

![프로젝트 저장·관리 ERD](C:/Users/Win11Pro/Documents/15_ai_data/_Final_Project/Documents/PA2_DB_ERD_발표용.png)

## 발표용 설명

> 프로젝트를 중심으로 입력 파일, CAD 분석 결과, 조립 순서를 연결해 저장합니다. 파일 자산은 해시로 식별해 재사용하고, 사용자가 확정한 순서는 초안과 별도 스냅샷으로 보관합니다. 기존 프로젝트를 열면 이 연결 정보를 이용해 작업을 복원합니다.

## 남긴 테이블

| 테이블 | 발표에서 설명할 역할 |
|---|---|
| `projects` | 프로젝트명과 버전, 현재 작업을 관리하는 중심 |
| `project_assets` | 어떤 프로젝트에서 어떤 파일을 입력했는지 연결 |
| `assets` | 파일 해시와 관리 경로를 저장하고 동일 파일 재사용 |
| `import_snapshots` | 프로젝트 버전별 CAD 분석 상태·결과 연결 |
| `plans` | 생성·편집 중인 조립 순서 초안 관리 |
| `confirmations` | 확정 당시 전체 순서를 JSON으로 보관 |

PK는 기본키, FK는 외래키이며 N은 0건 이상을 뜻한다. 하나의 프로젝트에 여러 입력·분석·계획이 연결되고, 하나의 계획에서 여러 확정본을 만들 수 있다. 파일 자산 하나를 여러 프로젝트 입력이 참조할 수 있다.

## 그림에서 생략한 내용

- 부품·그룹·접촉·단계별 순서, 차종·품종, 설정·작업·학습 테이블.
- `confirmations.project_id`의 직접 프로젝트 FK 등 추가 관계와 시간·진단 컬럼.
- `plans.input_snapshot_id` 등 앱의 ID 참조와 프로젝트의 현재 분석·초안·확정본 포인터.

그림은 전체 물리 스키마가 아니라 발표용으로 선택한 관계를 보여준다. `import_snapshots`는 분석 스냅샷의 관리 레코드이며, 부품·접촉 상세는 별도 테이블에 연결된다. `plans`의 단계별 정보도 별도 `plan_steps`에 저장한다.

STEP·BREP·MP4 본문은 DB가 아닌 파일 저장소에 보관한다. 원본 CAD를 직접 수정하지 않고 관리 사본을 사용한다. 기존 전체 ERD와 프로그램·DB는 변경하지 않았다.

## 파일

- [발표 삽입용 PNG](C:/Users/Win11Pro/Documents/15_ai_data/_Final_Project/Documents/PA2_DB_ERD_발표용.png)
- [확대·편집 가능한 SVG](C:/Users/Win11Pro/Documents/15_ai_data/_Final_Project/Documents/PA2_DB_ERD_발표용.svg)
- [전체 ERD 및 컬럼 명세](C:/Users/Win11Pro/Documents/15_ai_data/_Final_Project/Documents/PA2_DB_ERD.md)
