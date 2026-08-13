# Phase 진행 체크리스트 (계속)

> `PHASE0_CHECKLIST.md`, `PHASE1_CHECKLIST.md`에서 이어지는 실행 기록.
> Phase 2는 라벨링이 여러 세션에 걸쳐 진행되므로, 이 파일은 "다음 세션에
> 어디서부터 시작하면 되는지"를 바로 알 수 있게 세션별로 갱신한다.

---

## Phase 2 — 1차 20~30개 합성 케이스 작성 + 라벨링

**핵심 제약**: `human_label`/`human_note`는 사람(사용자)이 직접 판단해야
하는 값이라 Claude가 대신 채우지 않는다. Claude의 역할은 (a) 부족한
케이스 초안 작성, (b) 라벨링에 필요한 검토 자료(입력 대화·시스템 실제
판정·카테고리) 정리, (c) 사용자가 알려준 판단을 JSON에 반영하는 것까지.

### 케이스 신규 작성 (2026-08-13, 완료)

시작 전 실측: Triage 40 / Chart 19 / Schedule 20 / Followup 100 /
Orchestrator 23 / Reception 10 — "에이전트별 최소 20개" 기준으로 신규
작성이 실제로 필요한 건 Chart(+1)와 Reception(+10)뿐. 사용자가 "최소
배치"를 선택해 딱 그만큼만 작성:

- `chart_eval_cases.json`: "이물질 섭취 — 장폐색 의심 (소화기 응급)" 1개
  추가 (19→20)
- `reception_eval_cases.json`: 신규 10개 추가 (10→20) — 전화번호/개원시간/
  특정요일예약/교통위치/연중무휴/주말예약/무관질문×2/진료대상/마감임박예약
- `test_eval_cases_schema.py`의 기대 개수(chart 19→20, reception 10→20) 갱신
- lint 통과, 전체 스위트 149 passed 확인

### 라벨링 진행 상황

**진행 방식(사용자 확정)**: 5개씩 배치로 제시(입력 대화 + 시스템 실제
판정 + 카테고리를 마크다운으로 정리) → 사용자가 배치 단위로 PASS/FAIL/SKIP +
근거 회신 → Claude가 JSON에 반영 → 배치 끝날 때마다 계속할지 확인.

| 에이전트 | 목표 | 현재 라벨링 완료 | 상태 |
|---|---|---|---|
| **Triage** | 20 | **20 / 40** (배치 1~4 완료) | 목표 달성, 배치 5부터는 선택사항(YELLOW/GREEN 잔여 20개) |
| Chart | 20 | 0 / 20 | 미착수 |
| Schedule | 20 | 0 / 20 | 미착수 |
| Reception | 20 | 0 / 20 | 미착수 |
| Followup | 20 | 0 / 100 (표본만 필요) | 미착수 |
| Orchestrator | 20 | 0 / 23 | 미착수 |

**다음 세션 시작 지점**: Triage는 이미 20개(목표) 라벨링 완료 — 이어서
할지(배치 5, case 21~25, YELLOW/GREEN 등급) 다른 에이전트로 넘어갈지는
다음 세션 시작할 때 확인. 다른 에이전트로 넘어간다면 순서 제안: Chart →
Schedule → Reception → Orchestrator → Followup(표본 추출 방식 논의 필요 —
100개 중 20개를 어떻게 뽑을지 아직 미정, 다음 세션에서 확인 필요).

### Triage 라벨링 상세 (case 1~20 / 40)

| # | 케이스명 | 등급 | 라벨 | 근거 요약 |
|---|---|---|---|---|
| 1 | 발작 중 | RED | PASS | 발화가 지속 상태를 명확히 나타냄 |
| 2 | 심한 호흡곤란 | RED | PASS | 호흡 응급 신호 묘사 명확 |
| 3 | 의식불명 | RED | PASS | 반응 없음은 명시적 응급 신호 |
| 4 | 요도폐색 | RED | PASS | 성별 무관 증상 기반 판정 가능(엔진도 gender 미참고) |
| 5 | 자일리톨 섭취 | RED | PASS | 급성 저혈당 유발, 섭취량 불명확해도 응급 대응 맞음 |
| 6 | GDV 위염전 의심 | RED | PASS | 전형 증상 조합 일치, 고위험 품종 |
| 7 | 쇼크 | RED | PASS | 전형 신호(창백한 잇몸·약한 호흡·차가운 사지)와 일치 |
| 8 | 포도 섭취 | RED | PASS | 특이체질적 독성, 양 무관 즉시 대응 원칙 |
| 9 | 난산 | RED | PASS | 1시간 이상 진행 정체는 표준 응급 기준(확신도 다소 낮음) |
| 10 | 열사병 | RED | PASS | 전형 증상·원인·품종 설정 적절 |
| 11 | 중등도 호흡곤란 | ORANGE | PASS | RED 케이스와 강도 구분 명확 |
| 12 | 기도 협착음 | ORANGE | PASS | 불독+협착음 조합이 임상적으로 타당 |
| 13 | 혈성 비루 | ORANGE | PASS | 코피 단독, 동반 증상 없어 ORANGE 적절 |
| 14 | 혈변 | ORANGE | PASS | 반복 혈변, 동반 증상 없어 RED 격상 근거 없음 |
| 15 | 혈토 | ORANGE | PASS | 활성 출혈 진행 신호로 타당 |
| 16 | 의식 저하 | ORANGE | PASS | dull과 RED의 unresponsive 명확히 구분 |
| 17 | 얼굴 부종(알레르기) | ORANGE | PASS | 호흡곤란 언급 없어 정상 추론(확신 100%는 아님) |
| **18** | **초콜릿 섭취** | **ORANGE** | **FAIL** | **소형견+다량 섭취+증상 발현 조합이 RED에 더 가까움 — 처리방향 C(기록만 남김) 확정, 아래 참고** |
| 19 | 경도 호흡곤란 | YELLOW | PASS | "심하진 않다"는 표현이 RED/ORANGE보다 약함 |
| 20 | 잦은 기침 | YELLOW | PASS | 식욕 정상 유지, 흔한 임상 양상 |

**케이스 18(초콜릿 섭취) 처리 결정**: 옵션 C 선택(사용자 확정,
2026-08-13) — `expected_urgency`는 ORANGE 유지(현재 엔진과 일치),
`human_label=FAIL`과 근거는 그대로 유지. 발견한 구조적 gap(TOXIN 섹션이
물질명만으로 등급 고정, 섭취량·증상 중증도 미반영 — 초콜릿뿐 아니라
TOXIN 전체 해당)은 `EVAL_AGENT_REDESIGN_PLAN.md` 9번 섹션 Known Issues에
기록 완료. 엔진 로직은 고치지 않음(범위 밖).

### 라벨링 중 발견해 md에 기록한 것

1. Triage 엔진이 `gender` 등 프로필 정보를 전혀 참고하지 않음(케이스 4
   라벨링 중 발견) — md 9번 섹션 Known Issues.
2. TOXIN 섹션이 섭취량·증상 중증도를 반영 못하고 물질명만으로 등급
   고정(케이스 18 라벨링 중 발견) — md 9번 섹션 Known Issues.

### 코드 변경

- `backend/tests/evaluation/test_eval_cases_schema.py`: 라벨링 진행에 맞춰
  `human_label`이 항상 `None`이어야 한다는 가정을 "None이거나
  PASS/FAIL/SKIP 중 하나"로 완화. `human_label`이 있으면 `human_note`도
  비어있지 않아야 함을 추가 검증.

### 테스트 결과 (이번 세션 종료 시점)

- `python backend/scripts/lint_eval_cases.py` → 에러 0건, triage 20/40 라벨링됨
- `pytest -m "not live" -q` → **149 passed, 6 deselected**, 회귀 없음

### 다음 세션 방향 (사용자 확정, 2026-08-13)

- [x] Triage는 20/40으로 충분 — 나머지 20개(YELLOW 후반~GREEN)는 라벨링
      안 하고 다음 에이전트로 넘어감
- [ ] **다음 세션 시작**: Chart 라벨링(목표 20/20)부터 배치 1(케이스 1~5)
      진행
- [ ] Followup 표본 추출 기준은 다음 세션 시작할 때 논의 — 논의 전에
      먼저 `followup_eval_cases.json`에 카테고리 필드(`expected_category`)가
      있는지부터 확인하고 시작할 것(이미 `expected_category` 필드가 있는
      것으로 Phase 0/1에서 확인된 바 있으나, 실제 값 분포를 다시 보고
      카테고리별 균등 추출 여부를 정하기로 함)
- [x] 오늘 분 커밋 완료 — 커밋 해시는 아래 "커밋" 참고
