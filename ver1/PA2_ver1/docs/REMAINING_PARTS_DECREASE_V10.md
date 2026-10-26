# 수정 후 잔여 부품별 진단

생성 단계 32/64. 원본 결과: `planning-decrease-v10.json`.

아래는 확보한 최장 순서 끝 상태에서 검사한 **유한 직선 방향**의 결과입니다. 모든 가능한 이동 방법의 불가능 판정은 아닙니다. 차단에는 겹침 부피 재증가와 경로 충돌이 포함됩니다. 미판정은 충돌 확정이 아니며, 다른 상대에서 차단 근거가 확인되면 해당 방향의 최종 판정은 BLOCKED입니다.

| 부품 | 방향 수 | 차단 | 미판정 | 차단 상대(방향별 상이) | 차단 근거 | 미판정 근거 |
|---|---:|---:|---:|---|---|---|
| BLK-KD000 | 18 | 18 | 0 | BUS-KD200, MBD-KD000, NUT-FLGM5A #4 | 겹침 부피 재증가, 이동 경로 충돌 | — |
| BLT-WASM612A #1 | 10 | 9 | 1 | BUS-KD200, MBD-KD000 | 이동 경로 충돌, EXACT_COLLISION_WITNESS | 입력 정밀 검사/보정 한계 |
| BLT-WASM612A #2 | 10 | 9 | 1 | BUS-KD200, MBD-KD000 | 이동 경로 충돌, EXACT_COLLISION_WITNESS | 입력 정밀 검사/보정 한계 |
| BLT-WASM612A #3 | 10 | 9 | 1 | BUS-KD200 | 이동 경로 충돌, EXACT_COLLISION_WITNESS | 입력 정밀 검사/보정 한계 |
| BLT-WASM612A #4 | 10 | 9 | 1 | BLT-WASM620R #13, BUS-KD200, MBD-KD000 | 이동 경로 충돌, EXACT_COLLISION_WITNESS | 입력 정밀 검사/보정 한계 |
| BLT-WASM620R #12 | 12 | 12 | 0 | BUS-KD100, BUS-KD200 | 이동 경로 충돌, EXACT_COLLISION_WITNESS | — |
| BLT-WASM620R #13 | 12 | 12 | 0 | BUS-KD000, BUS-KD200, MBD-KD000 | 이동 경로 충돌 | — |
| BLT-WASM620R #21 | 12 | 12 | 0 | BUS-KD200, HVSC 2800 #2, MBD-KD000 | 겹침 부피 재증가, 이동 경로 충돌 | — |
| BUS-KD000 | 6 | 6 | 0 | BLT-WASM612A #2, BUS-KD200, NUT-FLGM5A #2 | 이동 경로 충돌 | — |
| BUS-KD100 | 6 | 6 | 0 | BLT-WASM612A #1, BUS-KD200, NUT-FLGM5A #1 | 이동 경로 충돌 | — |
| BUS-KD200 | 6 | 6 | 0 | BLT-WASM620R #12, MBD-KD000, NUT-FLGM5A #2, NUT-FLGM5A #3 | 이동 경로 충돌 | — |
| BUS-KD300 | 6 | 6 | 0 | BLT-WASM620R #13, BUS-KD200, MBD-KD000, NUT-FLGM5A #4 | 이동 경로 충돌 | — |
| HVSC 2800 #1 | 18 | 18 | 0 | BUS-KD200 | 이동 경로 충돌 | — |
| HVSC 2800 #2 | 18 | 18 | 0 | BUS-KD200, MBD-KD000 | 이동 경로 충돌, 겹침 부피 재증가 | — |
| LV CONT | 18 | 18 | 0 | BUS-KD200, NUT-FLGM5A #1, NUT-FLGM5A #3, NUT-FLGM5A #4 | 이동 경로 충돌 | — |
| NUT-FLGM5A #1 | 10 | 10 | 0 | BUS-KD100, BUS-KD200, MBD-KD000 | 이동 경로 충돌 | — |
| NUT-FLGM5A #2 | 10 | 10 | 0 | BUS-KD000, BUS-KD200, MBD-KD000 | 이동 경로 충돌 | — |
| NUT-FLGM5A #3 | 10 | 10 | 0 | BUS-KD200, MBD-KD000 | 이동 경로 충돌 | — |
| NUT-FLGM5A #4 | 10 | 10 | 0 | BUS-KD200, BUS-KD300, MBD-KD000 | 이동 경로 충돌 | — |
| RLY-KET400 #1 | 18 | 0 | 18 | — | — | 입력 정밀 검사/보정 한계 |
| RLY-KET400 #2 | 18 | 0 | 18 | — | — | 입력 정밀 검사/보정 한계 |
| source · 바디 1 | 20 | 20 | 0 | MBD-KD000, source · 바디 2 | 겹침 부피 재증가, 이동 경로 충돌 | — |
| source · 바디 2 | 20 | 20 | 0 | MBD-KD000 | 겹침 부피 재증가 | — |
| source · 바디 40 | 18 | 18 | 0 | MBD-KD000, NUT-FLGM5A #1, NUT-FLGM5A #2 | 이동 경로 충돌 | — |
| source · 바디 41 | 22 | 21 | 1 | BUS-KD200, HVSC 2800 #1, MBD-KD000, NUT-FLGM5A #1 | 이동 경로 충돌 | 곡면 이동 영역 미해결 |
| source · 바디 42 | 22 | 21 | 1 | BLK-KD000, MBD-KD000, NUT-FLGM5A #1 | 이동 경로 충돌 | 곡면 이동 영역 미해결 |
| source · 바디 43 | 22 | 22 | 0 | BLT-WASM620R #13, BLT-WASM620R #21, BUS-KD200, MBD-KD000, NUT-FLGM5A #1 | 이동 경로 충돌 | — |
| source · 바디 44 | 22 | 20 | 2 | BUS-KD000, BUS-KD200, MBD-KD000, NUT-FLGM5A #1, NUT-FLGM5A #3, NUT-FLGM5A #4 | 이동 경로 충돌 | 곡면 이동 영역 미해결, 시간 제한 |
| source · 바디 45 | 6 | 6 | 0 | MBD-KD000, NUT-FLGM5A #4 | 이동 경로 충돌, 겹침 부피 재증가 | — |
| source · 바디 46 | 6 | 6 | 0 | MBD-KD000, NUT-FLGM5A #3 | 이동 경로 충돌, 겹침 부피 재증가 | — |
| source · 바디 47 | 6 | 6 | 0 | MBD-KD000, NUT-FLGM5A #2 | 이동 경로 충돌, 겹침 부피 재증가 | — |
| source · 바디 48 | 6 | 6 | 0 | MBD-KD000, NUT-FLGM5A #1 | 이동 경로 충돌, 겹침 부피 재증가 | — |

부품별 방향 벡터·거리·상대 ID·보정 수치는 요약 JSON의 `remaining[].candidates`에 보관합니다.
