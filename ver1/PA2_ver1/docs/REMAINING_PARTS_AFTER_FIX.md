# 수정 후 잔여 부품별 진단

생성 단계 20/64. 원본 결과: `planning-binary-final.json`.

아래는 확보한 최장 순서 끝 상태에서 검사한 **유한 직선 방향**의 결과입니다. 모든 가능한 이동 방법의 불가능 판정은 아닙니다. 미판정은 충돌 확정이 아니며, 다른 상대 부품에서 실제 충돌이 확인되면 해당 방향의 최종 판정은 BLOCKED입니다.

| 부품 | 방향 수 | 충돌 | 미판정 | 차단 상대(방향별 상이) | 미판정 근거 |
|---|---:|---:|---:|---|---|
| BLK-KD000 | 18 | 18 | 0 | BUS-KD200, COV-KD000, MBD-KD000, NUT-FLGM5A #4 | — |
| BLT-WASM612A #1 | 10 | 10 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| BLT-WASM612A #2 | 10 | 10 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| BLT-WASM612A #3 | 10 | 10 | 0 | BUS-KD200, COV-KD000 | — |
| BLT-WASM612A #4 | 10 | 10 | 0 | BLT-WASM620R #13, BUS-KD200, COV-KD000, MBD-KD000 | — |
| BLT-WASM620R #11 | 12 | 12 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| BLT-WASM620R #12 | 12 | 12 | 0 | BUS-KD200, COV-KD000 | — |
| BLT-WASM620R #13 | 12 | 12 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| BLT-WASM620R #14 | 12 | 12 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| BLT-WASM620R #15 | 12 | 12 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| BLT-WASM620R #16 | 12 | 12 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| BLT-WASM620R #17 | 12 | 12 | 0 | BUS-KD200, COV-KD000 | — |
| BLT-WASM620R #18 | 12 | 12 | 0 | COV-KD000, MBD-KD000, NUT-FLGM5A #1 | — |
| BLT-WASM620R #19 | 12 | 12 | 0 | BUS-KD200, COV-KD000, MBD-KD000, NUT-FLGM5A #3 | — |
| BLT-WASM620R #20 | 12 | 12 | 0 | BUS-KD200, COV-KD000, MBD-KD000, NUT-FLGM5A #2 | — |
| BLT-WASM620R #21 | 12 | 12 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| BLT-WASM620R #22 | 12 | 12 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| BLT-WASM620R #23 | 12 | 12 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| BUS-KD000 | 6 | 6 | 0 | BUS-KD200, COV-KD000, NUT-FLGM5A #2 | — |
| BUS-KD100 | 6 | 6 | 0 | BUS-KD200, COV-KD000, NUT-FLGM5A #1 | — |
| BUS-KD200 | 6 | 6 | 0 | COV-KD000, MBD-KD000, NUT-FLGM5A #2, NUT-FLGM5A #3 | — |
| BUS-KD300 | 6 | 6 | 0 | BUS-KD200, COV-KD000, MBD-KD000, NUT-FLGM5A #4 | — |
| COV-KD000 | 18 | 18 | 0 | SEL-KD000 | — |
| HVSC 2800 #1 | 18 | 18 | 0 | COV-KD000 | — |
| HVSC 2800 #2 | 18 | 18 | 0 | COV-KD000 | — |
| LV CONT | 18 | 18 | 0 | COV-KD000, NUT-FLGM5A #1, NUT-FLGM5A #3, NUT-FLGM5A #4 | — |
| NUT-FLGM5A #1 | 10 | 10 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| NUT-FLGM5A #2 | 10 | 10 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| NUT-FLGM5A #3 | 10 | 10 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| NUT-FLGM5A #4 | 10 | 10 | 0 | BUS-KD200, COV-KD000, MBD-KD000 | — |
| RLY-KET400 #1 | 18 | 0 | 18 | — | 입력 정밀 검사/보정 한계 |
| RLY-KET400 #2 | 18 | 0 | 18 | — | 입력 정밀 검사/보정 한계 |
| SEL-KD000 | 18 | 18 | 0 | COV-KD000, MBD-KD000 | — |
| source · 바디 1 | 20 | 15 | 5 | COV-KD000, MBD-KD000 | 초기 영역 차감 형상 무효, 곡면 이동 영역 미해결 |
| source · 바디 2 | 20 | 20 | 0 | COV-KD000, MBD-KD000 | — |
| source · 바디 40 | 18 | 18 | 0 | COV-KD000, MBD-KD000, NUT-FLGM5A #1, NUT-FLGM5A #2 | — |
| source · 바디 41 | 22 | 22 | 0 | BUS-KD200, COV-KD000, MBD-KD000, NUT-FLGM5A #1 | — |
| source · 바디 42 | 22 | 22 | 0 | COV-KD000, MBD-KD000, NUT-FLGM5A #1, SEL-KD000 | — |
| source · 바디 43 | 22 | 22 | 0 | BUS-KD200, COV-KD000, MBD-KD000, NUT-FLGM5A #1 | — |
| source · 바디 44 | 22 | 22 | 0 | BUS-KD200, COV-KD000, MBD-KD000, NUT-FLGM5A #1, NUT-FLGM5A #3, NUT-FLGM5A #4 | — |
| source · 바디 45 | 6 | 6 | 0 | COV-KD000, MBD-KD000, NUT-FLGM5A #4 | — |
| source · 바디 46 | 6 | 6 | 0 | COV-KD000, MBD-KD000, NUT-FLGM5A #3 | — |
| source · 바디 47 | 6 | 6 | 0 | COV-KD000, MBD-KD000, NUT-FLGM5A #2 | — |
| source · 바디 48 | 6 | 6 | 0 | COV-KD000, MBD-KD000, NUT-FLGM5A #1 | — |

부품별 방향 벡터·거리·상대 ID·보정 수치는 요약 JSON의 `remaining[].candidates`에 보관합니다.
