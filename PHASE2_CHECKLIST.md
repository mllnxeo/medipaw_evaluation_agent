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
| **Triage** | 20 | **20 / 40** (배치 1~4 완료, 2026-08-13) | 완료, 잔여 20개(YELLOW 후반~GREEN)는 라벨링 안 함(사용자 결정) |
| **Chart** | 20 | **20 / 20** (배치 1~4 완료, 2026-08-14) | 완료 |
| **Schedule** | 20 | **20 / 20** (배치 1~4 완료, 2026-08-14) | 완료 |
| **Reception** | 20 | **20 / 20** (배치 1~4 완료, 2026-08-14) | 완료 |
| **Followup** | 20 | **20 / 100**(표본 추출, 배치 1~4 완료, 2026-08-16) | 완료 |
| **Orchestrator** | 20 | **23 / 23** (배치 1~4 완료, 2026-08-16) | 완료(목표 20 초과 달성, 전체 라벨링) |

## Phase 2 완료 (2026-08-16)

6개 에이전트 전부 라벨링 완료 — Triage 20/40, Chart 20/20, Schedule
20/20, Reception 20/20, Followup 20/100(표본), Orchestrator 23/23.
총 **123개 케이스**에 사람 라벨링 완료. 데이터/케이스 오류 **9건**을
발견해 직접 수정(Chart 2건, Reception 1건 도구 매칭 + 1건 이름표,
Orchestrator 3건 후보군 혼동 + 1건 이름표, Followup은 케이스 수정 없이
시스템 쪽 문제로 판명). 시스템(평가 대상 에이전트 + 평가 로직 자체)
한계 발견 **8건**을 `EVAL_AGENT_REDESIGN_PLAN.md` 9번 섹션 Known
Issues에 기록(gender 미반영, TOXIN 중증도 미반영, Chart urgency
무검증, DURATION_PROMPT 예시 부재, GREEN 범위 협소, Reception null
계열, case_eval.py rule 체크 테스트 계획 부재, **Followup severity
검증 공백[우선순위: 높음]**).

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

### Chart 라벨링 상세 (case 1~20 / 20, 전체 완료)

| # | 케이스명 | 등급(원본→최종) | 라벨 | 근거 요약 |
|---|---|---|---|---|
| 1 | 구토·식욕저하 | YELLOW | PASS | 혈변/혈뇨 없음이 명시적으로 확인됨 |
| 2 | 다리 절음 | YELLOW | PASS | urgency는 Chart 평가에 영향 없음 확인, 입력은 SOAP 키워드 유도에 적절 |
| 3 | 피부 가려움 | GREEN | PASS | 만성 전형적 알레르기 패턴 |
| 4 | 심장 질환 | ORANGE | PASS | 카발리에+승모판막질환 조합 타당, 안정 시 호흡곤란 없어 ORANGE |
| 5 | 발작 | RED | PASS | 반복 발작+회복 후 혼미는 명확한 응급 |
| 6 | 안구 충혈 | YELLOW | PASS | 5일 지속 결막염 계열, YELLOW 적절 |
| 7 | 예방접종 | GREEN | PASS | 특이 증상 없는 정기 접종 |
| 8 | 고양이 반복 구토 | YELLOW | PASS | 2주 만성 구토+체중감소, YELLOW 적절 |
| **9** | **고양이 호흡곤란** | **ORANGE→RED(수정)** | **FAIL** | **구강호흡 시도+복식호흡 red_flag가 이미 있는데 ORANGE는 등급 오류로 판단, RED로 직접 수정** |
| 10 | 교통사고 외상 | ORANGE | PASS | 의식 있고 쇼크 징후 없어 ORANGE 적절 |
| 11 | 신장 질환 의심 | YELLOW | PASS | 만성 신장질환 의심 소견, 급성 아님 |
| 12 | 당뇨 의심 | YELLOW | PASS | 11번과 유사한 만성 대사질환 패턴 |
| 13 | 외이염 | GREEN | PASS | 코커스패니얼 호발견종, 경증 |
| **14** | **아나필락시스 의심** | **ORANGE(유지)** | **FAIL** | **급속 진행+호흡 이상 겹쳐 RED 여지 있으나 확신 부족 — 등급 안 고치고 "전문가 검토 필요한 경계 케이스"로만 기록** |
| 15 | 고양이 요도폐색 | RED | PASS | 6시간 배뇨 불능은 명백한 RED 기준 |
| 16 | 구강 질환-치주염 | GREEN | PASS | 수개월 만성 치과 문제 |
| 17 | 관절염-노령견 | YELLOW | PASS | 등급 적절, 다만 챗봇 응답이 소견성 발언(대화 스타일 이슈, 별도 기록) |
| 18 | 결막염 | GREEN | PASS | 경증 전형적 결막염 |
| **19** | **척추 디스크 악화** | **ORANGE→RED(수정)** | **FAIL** | **뒷다리 마비+배뇨 불능 red_flag 있는데 ORANGE는 9번과 같은 패턴의 등급 오류, RED로 직접 수정** |
| 20 | 이물질 섭취-장폐색 의심(신규 작성 케이스) | ORANGE | PASS | 쇼크·무기력·창백함 없어 ORANGE 적절 |

**케이스 9·19 처리**: `urgency_level`을 ORANGE→RED로 **직접 수정**(사용자
결정, Triage 케이스 18과 달리 "케이스 품질 문제이므로 바로 고치는 게 맞다"고
판단). Chart 평가 자체는 이 값을 검증하지 않지만(아래 Known Issue 참고),
골든 데이터셋 품질 차원에서 수정.

**케이스 14 처리**: 등급(ORANGE) 그대로 유지, human_note에 "전문가 검토
필요한 경계 케이스"로 표시만 하고 임의로 고치지 않음 — 9·19번과 달리
완화 표현("좀")이 있어 확신도가 낮았기 때문.

### 라벨링 중 발견해 md에 기록한 것

1. Triage 엔진이 `gender` 등 프로필 정보를 전혀 참고하지 않음(케이스 4
   라벨링 중 발견, 2026-08-13) — md 9번 섹션 Known Issues.
2. TOXIN 섹션이 섭취량·증상 중증도를 반영 못하고 물질명만으로 등급
   고정(케이스 18 라벨링 중 발견, 2026-08-13) — md 9번 섹션 Known Issues.
3. Chart 평가가 입력 `triage.urgency_level`의 타당성을 전혀 검증하지 않음
   — `ChartAgent`가 이 값을 프롬프트에 그대로 꽂아 넣을 뿐 아무 검증도
   안 함(케이스 9 라벨링 중 발견, 2026-08-14) — md 9번 섹션 Known Issues.
   앞의 두 건과 달리 "규칙의 한계"가 아니라 "검증 규칙 자체의 부재"이고,
   영향 범위도 Chart 에이전트가 받는 모든 triage 입력 전체.

### 코드 변경

- `backend/tests/evaluation/test_eval_cases_schema.py`: 라벨링 진행에 맞춰
  `human_label`이 항상 `None`이어야 한다는 가정을 "None이거나
  PASS/FAIL/SKIP 중 하나"로 완화. `human_label`이 있으면 `human_note`도
  비어있지 않아야 함을 추가 검증.

### 테스트 결과 (2026-08-13 세션 종료 시점)

- `python backend/scripts/lint_eval_cases.py` → 에러 0건, triage 20/40 라벨링됨
- `pytest -m "not live" -q` → **149 passed, 6 deselected**, 회귀 없음

### 테스트 결과 (2026-08-14 세션 종료 시점)

- `python backend/scripts/lint_eval_cases.py` → 에러 0건, triage 20/40 +
  **chart 20/20** 라벨링됨
- `pytest -m "not live" -q` → **149 passed, 6 deselected**, 회귀 없음

### Chart 라벨링 방법론 결정 (사용자 확정, 2026-08-14)

Chart는 Triage와 달리 무료 결정론적 엔진이 없음 — `_check_soap_sections`
등은 실제 `ChartAgent.generate()` 출력을 대상으로 하는 체크라, "시스템
판정"을 보려면 케이스당 LLM 호출(비용)이 필요함. 두 가지 방식을 제안해
사용자가 선택:
- **채택**: 입력(pet/triage/chat_history) + 기대값(expected_keywords,
  forbidden_phrases)만 보고 "케이스가 골든 데이터셋으로 타당한가"만
  판단. ChartAgent는 호출하지 않음(무료).
- 이유(사용자 설명): 지금 라벨링은 케이스 자체의 타당성만 보는 것이고,
  시스템이 실제로 뭐라고 답하는지 미리 보면 판단이 오염될 수 있어 Phase
  3(judge 일치율 측정)에서 처음 시스템 출력을 보기로 함. Triage 배치에서
  시스템 계산 결과를 같이 보여준 것과는 성격이 다름(그건 결정론적
  엔진이라 무료였고, expected_extracted가 곧 엔진 입력이라 사실상
  같은 데이터의 다른 표현이었음 — Chart처럼 "생성 결과"를 미리 보여주는
  것과는 다름).

### 다음 세션 방향 (사용자 확정, 2026-08-13) — 완료

- [x] Triage는 20/40으로 충분 — 나머지 20개(YELLOW 후반~GREEN)는 라벨링
      안 하고 다음 에이전트로 넘어감
- [x] Chart 라벨링(목표 20/20) 배치 1~4 완료 (2026-08-14)
- [ ] Followup 표본 추출 기준 — 아직 미착수, 아래 참고
- [x] 2026-08-13분 커밋 완료 — `8229ab1` "feat(evaluation): Triage 라벨링
      20개 완료 + Chart·Reception 케이스 보강"

### 다음 세션 방향 (2026-08-14 세션 종료 시점)

- [x] Chart 20/20 라벨링 완료(PASS 17, FAIL 3 — 9·14·19번은 위 표 참고)
- [x] 케이스 9·19의 `urgency_level`을 ORANGE→RED로 직접 수정, 케이스 14는
      경계 케이스로 기록만(등급 유지)
- [x] Schedule 라벨링 진행 중 — 배치 1~2 완료(case 1~10/20), 배치 3부터
      이어서 진행
- [ ] Followup 표본 추출 기준은 Schedule·Reception·Orchestrator 끝난 뒤
      논의 — 논의 전에 먼저 `followup_eval_cases.json`에
      `expected_category` 필드 값 분포를 확인하고 카테고리별 균등 추출
      여부를 정하기로 함(Phase 0/1에서 필드 존재 자체는 확인됨)
- [x] 이번 세션분 커밋 완료 — `a152be7` "feat(evaluation): Chart 라벨링
      20개 완료(전체), 등급 오류 2건 직접 수정"
- [x] Schedule 20/20 라벨링 완료, 커밋 완료 — `b54918a`
      "feat(evaluation): Schedule 라벨링 20개 완료, GREEN 등급 범위
      설계 문제 발견"
- [x] Reception 20/20 라벨링 완료, 커밋 완료 — `0ce79e7`
      "feat(evaluation): Reception 라벨링 20개 완료, 도구 매칭 오류
      1건 수정"
- [x] Orchestrator 23/23 라벨링 완료, 커밋 완료 — `6bc8c25`
      "feat(evaluation): Orchestrator 라벨링 23개 완료, 케이스 오류
      3건 수정"
- [x] Followup 20/100(표본) 라벨링 완료, 커밋 완료 — `72fc4b1`
      "feat(evaluation): Followup 라벨링 완료, 골든 데이터셋 123개
      확보" — **Phase 2 전체 완료**

### Schedule 라벨링 상세 (case 1~10 / 20, 진행 중)

| # | 케이스명 | urgency | 라벨 | 근거 요약 |
|---|---|---|---|---|
| 1 | RED — 발작 (초진) | RED | PASS | 기본+초진가산+신경계가산 규칙과 부합 |
| 2 | RED — 복합 외상 (재진) | RED | PASS | 재진 가산 없음보다 다발외상 복잡도 가산이 커서 순증가 — 코드로 확인 |
| 3 | RED — 요도폐색 고양이 (초진) | RED | PASS | 복잡도 가산 리스트에 명시적으로 포함 |
| 4 | RED — GDV 위염전 대형견 (초진) | RED | PASS | 초진+GDV복잡도+대형견 체중가산 겹쳐 타 RED보다 긴 범위 |
| 5 | RED — 열사병 (초진) | RED | PASS | 체중 가산 구간 밖이라 가산 없음, 하한 짧은 것도 자연스러움 |
| 6 | ORANGE — 중등도 호흡곤란 (초진) | ORANGE | PASS | 기본+초진+체중(5kg미만)+중등도 복잡도 조합 부합 |
| **7** | **ORANGE — 위확장 의심 (초진)** | ORANGE | PASS | **GDV 복잡도가산 적용은 맞으나, 기대범위 하한(40)이 최소 계산값(~55)보다 낮아 판별력 약함** |
| 8 | ORANGE — 혈토 (초진) | ORANGE | PASS | 위장출혈은 최상위 복잡도 아니라 중등도 가산 |
| 9 | ORANGE — 고양이 혈변 (초진) | ORANGE | PASS | 8번과 동일 패턴, 범위도 동일 |
| **10** | **YELLOW — 잦은 기침 (재진)** | YELLOW | PASS | **경증+재진+체중가산 조합의 계산값(~35~40)보다 기대범위 하한(20)이 낮아 판별력 약함(7번과 동일 패턴)** |
| **11** | **YELLOW — 피부 알레르기 고양이 (초진)** | YELLOW | PASS | **계산상 40~50 근처, 기대범위(20~45) 상한과 아슬아슬하게 맞음** |
| 12 | YELLOW — 혈뇨 고양이 (초진) | YELLOW | PASS | 계산상 40~55, 기대범위(20~50)와 대체로 부합 |
| **13** | **YELLOW — 경추 디스크 증상 (재진)** | YELLOW | **FAIL** | **DURATION_PROMPT "경련·신경계" 항목에 예시가 없어 추간판탈출증 같은 경계 질환의 복잡도 분류가 LLM 재량 — 프롬프트 설계 모호함, 아래 참고** |
| **14** | **YELLOW — 반복 구토 고양이 (초진)** | YELLOW | PASS | **계산상 40~50, 기대범위(20~45) 상한과 아슬아슬하게 맞음** |
| 15 | GREEN — 정기 건강검진 (재진) | GREEN | PASS | 계산상 30, 기대범위(20~40)에 편하게 들어옴 |
| **16** | **GREEN — 연간 예방접종 (재진)** | GREEN | **FAIL** | **GREEN 범위 폭 체계적 협소함(메모 B) — 계산값(35)이 상한(35)에 정확히 닿음** |
| **17** | **GREEN — 중성화 수술 전 검진 (초진)** | GREEN | **FAIL** | **GREEN 범위 폭 체계적 협소함(메모 B) — 계산값(40~50)이 상한(40)과 거의 붙거나 넘음** |
| **18** | **GREEN — 기침 경과 관찰 (재진)** | GREEN | **FAIL** | **GREEN 범위 폭 체계적 협소함(메모 B) — 계산값(35~40)이 상한(35)과 거의 붙거나 넘음** |
| **19** | **GREEN — 구강 위생 상담 (초진)** | GREEN | **FAIL** | **GREEN 범위 폭 체계적 협소함(메모 B) — 계산값(40~50)이 상한(40)과 거의 붙거나 넘음** |
| **20** | **GREEN — 고양이 정기 검진 (재진)** | GREEN | **FAIL** | **GREEN 범위 폭 체계적 협소함(메모 B) — 계산값(35~40)이 상한(40)에 맞닿음** |

**Schedule 라벨링 완료 (20/20, 2026-08-14)**: PASS 13, FAIL 7(13번
DURATION_PROMPT 모호함 1건 + 16·17·18·19·20번 GREEN 협소 패턴 5건 +
아래 메모 A 관련 없음 — 7·10·11·14번은 PASS로 유지, human_note에만
경고 기록). **GREEN 6개 중 5개(83%)**가 범위 협소 패턴 FAIL — GREEN
중 유일하게 통과한 건 "정기 건강검진"(15번) 1건뿐.

**케이스 13 처리**: `human_label=FAIL`, `expected_duration_min/max`는
건드리지 않음(케이스 자체가 아니라 프롬프트 설계의 모호함이 원인이라
판단). `EVAL_AGENT_REDESIGN_PLAN.md` 9번 섹션 Known Issues에 기록 —
"경련·신경계" 구간만 "안구 응급"과 달리 예시가 없어, 경계 질환의 복잡도
분류가 LLM 재량에 맡겨짐. gender·TOXIN 건과 달리 **재현성 문제**로
이어질 수 있다는 점이 다름.

**Phase 6용 누적 메모 A — "범위 하한이 계산 최솟값보다 낮아 판별력이
약함(범위가 넓은 방향의 문제)" (2026-08-14 갱신)**: 7·10·11·14번,
**Schedule 20개 중 4개**에서 기대범위 하한이 실제 계산 가능한 최솟값보다
낮게 잡혀 있어(11번은 추가로 계산 최솟값이 상한에도 바짝 붙음), 범위가
필요 이상으로 넓어 판별력이 약한 패턴이 반복 발견됨. 개별 케이스 저작
실수인지, 이 골든셋의 소요시간 범위를 정한 방식 자체가 전반적으로
경향성을 갖는지는 지금 단계(입력+기대값만 보는 무료 검토)에서는 판단할
수 없음 — Phase 6(임계값 확정, 실측 기반)에서 `estimate_duration()`을
실제로 반복 실행해 계산값 분포를 확인할 때 이 4개 케이스를 우선적으로
재검토하기로 함.

**Phase 6용 누적 메모 B — "GREEN 등급 범위 폭이 다른 등급 대비
체계적으로 좁음(범위가 좁은 방향의 문제)" (2026-08-14 최종)**: 메모 A와
원인·방향이 반대라 별도 관리. **최종: GREEN 6개 중 5개(83%)가
human_label=FAIL** — GREEN 중 유일하게 통과한 건 "정기 건강검진"(15번)
1건뿐. 상세 통계와 근거는 `EVAL_AGENT_REDESIGN_PLAN.md` 9번 섹션 Known
Issues 참고(등급별 평균 범위 폭: RED 26.0 / ORANGE 25.0 / YELLOW 24.0 /
GREEN 20.8). Phase 6에서 메모 A와 함께 재검토 — 특히 GREEN 등급
`expected_duration_max`는 실측 기반으로 재산정이 사실상 필요해 보임.

### Reception 라벨링 완료 (20/20, 2026-08-14)

| # | 케이스명 | 기대 도구(원본→최종) | 라벨 | 근거 요약 |
|---|---|---|---|---|
| 1 | 병원 위치 질문 | get_hospital_info | PASS | 위치 질문과 도구명 명확히 대응 |
| 2 | 운영시간 질문 | get_operating_hours | PASS | 운영시간 질문과 도구명 명확히 대응 |
| 3 | 예약 슬롯 질문 | find_open_slots | PASS | 빈 슬롯 조회 의도로 자연스러움 |
| 4 | 주소 표현 변형 | get_hospital_info | PASS | 1번의 표현 변형 짝 |
| 5 | 진료시간 표현 변형 | get_operating_hours | PASS | 2번의 표현 변형 짝 |
| 6 | 빈 슬롯 표현 변형 | find_open_slots | PASS | 3번의 표현 변형 짝 |
| 7 | 무관 질문(날씨) | null | PASS | 완전히 무관, null 명백 |
| **8** | **무관 질문(음식)** | null | PASS | **null은 타당하나 건강/사양관리 계열 질문 — 아래 참고** |
| 9 | 의사 소개 질문 | get_hospital_info | PASS | 원장 소개, 병원 정보 조회로 대응 |
| 10 | 휴진 여부 질문 | get_operating_hours | PASS | 운영시간 문의의 자연스러운 변형 |
| 11 | 전화번호 질문 | get_hospital_info | PASS | 병원 정보 조회로 자연스럽게 대응 |
| 12 | 개원 시간 질문 | get_operating_hours | PASS | 운영시간 조회로 자연스럽게 대응 |
| 13 | 특정 요일 예약 질문 | find_open_slots | PASS | 빈 슬롯 조회로 자연스럽게 대응 |
| **14** | **위치 접근성 질문**(원래 "위치 표현 변형(교통)") | get_hospital_info | PASS | **도구 판정은 맞으나 케이스 이름표가 실제 성격과 안 맞아 이름 수정(아래 참고)** |
| 15 | 연중무휴 질문 | get_operating_hours | PASS | 운영시간 조회로 자연스럽게 대응 |
| 16 | 주말 예약 질문 | find_open_slots | PASS | 빈 슬롯 조회로 자연스럽게 대응 |
| **17** | **무관 질문(동물 등록)** | null | PASS | **null은 타당하나 8번과 같은 계열 — 아래 참고** |
| 18 | 무관 질문(사료 추천) | null | PASS | 8번과 동일 패턴 |
| 19 | 진료 대상 질문 | get_hospital_info | PASS | 병원 정보 조회로 자연스럽게 대응 |
| **20** | **마감 임박 예약 질문** | **get_operating_hours→find_open_slots(수정)** | **FAIL** | **"마지막 예약 시간"은 운영시간만으론 못 답함 — 빈 슬롯 조회가 맞아 도구 자체를 직접 수정** |

**케이스 14 처리**: `name` 필드를 "위치 표현 변형(교통)" → "위치 접근성
질문"으로 직접 수정(2026-08-14) — 도구 판정 자체는 맞았지만, 실제
질문은 위치가 아니라 교통 접근성을 묻는 별개의 하위 질문이라 이름표가
잘못 붙어 있었음. 시스템 한계가 아니라 케이스 이름표 오류라 바로 수정.

**케이스 20 처리**: `expected_tool`을 `get_operating_hours`→
`find_open_slots`로 직접 수정(2026-08-14) — "오늘 마지막 예약은 몇
시예요?"는 병원 마감시간이 아니라 실제 빈 슬롯 데이터가 필요한 질문이라
원래 기대 도구가 명백히 잘못 매칭돼 있었음. Chart 9·19번과 같은 성격의
"케이스 자체 오류 → 직접 수정" 케이스.

**케이스 8·17·18 처리**: `expected_tool=null` 자체는 타당해 human_label은
전부 PASS 유지. 다만 "건강/사양관리·부가서비스 관련 질문이 순수 잡담과
동일하게 null 처리된다"는 공통점을 발견해 `EVAL_AGENT_REDESIGN_PLAN.md`
9번 섹션 Known Issues에 3건 묶어서 기록(도구 체계를 바꾸는 문제가 아니라
향후 라우팅 로직 개선 아이디어).

**표현 변형 짝 메모(Phase 9용)**: Reception 재진술 짝(같은 의도를 다른
말로 재구성한 케이스)은 최종적으로 **3쌍**뿐(1·4번 "위치/주소", 2·5번
"운영시간/진료시간", 3·6번 "예약 슬롯/빈 슬롯"). 나머지는 같은 도구
안에서도 서로 다른 하위 질문으로 설계돼 재진술 짝이 아님. 지금 늘리지
않고, 필요시 **Phase 9(100개 확장)** 때 재진술 짝을 추가할지 검토하기로
함.

### Orchestrator 라벨링 완료 (23/23, 2026-08-16)

목표(20개)를 초과해 **23개 전부** 라벨링. `route()`는 pill/`active_flow`
상태(SCHEDULING·AWAITING_BOOKING_CONFIRM 등)에 대해 LLM 호출 없는
결정론 분기가 있어, 해당 케이스(8~11번)는 코드 확인만으로 100% 확실하게
검증함 — 나머지는 Chart/Schedule/Reception과 동일하게 `_llm_pick()`이
LLM 호출이라 입력+기대값만으로 검토.

| # | 케이스명 | 라벨 | 근거 요약 |
|---|---|---|---|
| 1 | BOOKED — 증상 경과 보고 | PASS | 아이 상태 관련 대화 규칙과 일치 |
| **2** | **BOOKED — 병원 운영시간 질문** | **FAIL** | **allowed를 [reception,followup_filter]→[reception]으로 수정 — 아래 "구조 오류" 참고** |
| 3 | BOOKED — 주차 안내 질문 | PASS | 순수 병원 정보, reception |
| 4 | BOOKED — 예약 시간 변경 요청 | PASS | 예약 변경 규칙과 일치 |
| 5 | BOOKED — 증상 악화 보고 | PASS | followup_filter 내부 자체 응급 감지 로직 확인, gap 아님 |
| 6 | BOOKED — 수의사 소개 질문 | PASS | 순수 병원 정보, reception |
| **7** | **BOOKED — 잡담 (무관 주제)** | **FAIL** | **allowed를 [redirect,reception]→[reception]으로 수정 — BOOKED phase는 구조적으로 redirect 불가** |
| 8 | SCHEDULING — 슬롯 선택 고정 | PASS | 결정론 분기, 100% 확실 |
| 9 | SCHEDULING — 다른 날짜 요청 | PASS | 결정론 분기, 100% 확실 |
| 10 | 예약확인 게이트 — 네 | PASS | 결정론 분기, 100% 확실 |
| 11 | 예약확인 게이트 — 아니요 | PASS | 결정론 분기, 100% 확실 |
| 12~17 | PRE — 발작/호흡이상/독성섭취/구토/위치/전화번호 | PASS | 증상은 triage, 병원정보는 reception 규칙과 일치 |
| 18 | PRE — 예약 바로 원함 (문진 없이) | PASS | "예약은 문진 필수" 규칙과 일치 |
| 19 | PRE — 잡담 | PASS | allowed 2값[reception,redirect] 유지 — 애매한 영역으로 기록만(아래 참고) |
| **20** | **일반 케어 질문(사료)**(원래 "PRE — 무관 질문") | **FAIL** | **name+allowed 모두 수정 — 아래 참고** |
| 21~22 | TRIAGING — 문진 중 증상 답변/추가 증상 | PASS | 문진 계속 규칙과 일치 |
| 23 | TRIAGING — 문진 중 화제 전환 (병원 위치) | PASS | 문진 중 이탈 처리 검증하는 좋은 케이스 |

**"구조적 후보군 vs 실제 정답" 혼동 오류 — 2·7·20번, 총 3건**: 사용자가
2번에서 처음 패턴을 지적한 뒤, 나머지 22개를 전수 스캔해 6번(재검토 결과
정상), 19번(애매하나 보류), 20번(추가 확정)까지 확인. `_candidates()`가
반환하는 phase별 구조적 후보군 전체(또는 다른 phase의 후보군)를 그대로
`allowed`에 넣어놓고, 실제로는 phase_hint가 특정 답 하나로 좁혀야 하는
케이스들이었음:
- **2번**: BOOKED phase_hint "순수 병원 정보만 reception"인데
  `[reception, followup_filter]`(BOOKED 구조적 후보군 그대로) — `allowed`를
  `[reception]`으로 수정.
- **7번**: BOOKED phase는 `_candidates()`가 절대 `redirect`를 반환 안 함
  (`router.py:152` 주석 "triage·redirect 불가")인데 `[redirect, reception]`
  — `allowed`를 `[reception]`으로 수정. 채점에 실질적 해는 없었음(애초에
  안 나올 값이라).
- **20번**: PRE_BOOKING phase_hint "사료 추천 같은 일반 케어 질문은
  reception"인데 `[redirect, reception]` — `allowed`를 `[reception]`으로
  수정. 케이스 이름도 "무관 질문"에서 실제 성격에 맞게 "일반 케어
  질문(사료)"로 수정(이름표 오류까지 이중 오류).
- **19번(보류)**: `[reception, redirect]` 2값 유지지만, 순수 잡담엔
  phase_hint가 구체적으로 규정한 바가 없어 "명백한 오류"로 단정하지
  않고 애매함만 기록. Phase 3(judge 일치율) 또는 Phase 6에서 실측
  기반으로 재검토 여지 있음.

**세션 중 발견한 진행 실수**: 배치 1→2 전환 시 번호를 잘못 세어 6번
케이스(수의사 소개 질문)를 건너뛸 뻔함 — 사용자가 "7~11번이 아직 판단
전인 것 같다"고 지적해 발견, 실제 파일 인덱스로 재확인 후 정정.
라벨 자체는 메시지 텍스트로 정확히 매칭해 반영했기 때문에 데이터 오염은
없었음.

### Followup 표본 추출 기준 (2026-08-16)

100개 중 20개를 라벨링 대상으로 추출. 먼저 `followup_eval_cases.json`의
분류 필드를 확인:
- `expected_category`(8종): symptom_change 20 / pet_general 15 /
  appetite_energy 12 / medication_response 11 / pain_behavior 11 /
  hospital_info 11 / stool_urine 10 / irrelevant 10
- `expected_severity`(3종): stable 51 / worse 41 / **urgent_possible 8**
- `urgent_possible` 8개는 `symptom_change`(4)·`stool_urine`(4) 단 2개
  카테고리에만 몰려 있고, 나머지 6개 카테고리엔 전무.

**결정: 무작위/카테고리 균등 대신 severity 우선 추출.** 근거(사용자
판단) — `EVAL_AGENT_REDESIGN_PLAN.md` 4번 섹션 "hard gate(응급도 등)는
recall 100%를 목표로 먼저 고정한다" 원칙과 일치시키기 위해, 희소하지만
안전상 중요한 `urgent_possible`이 표본에서 누락되지 않는 걸 카테고리
균등 배분보다 우선했다. 카테고리 균등 추출(8개×2~3개)을 했다면
`urgent_possible` 8개 중 상당수가 표본 밖으로 빠질 위험이 있었음.

**추출 방법**: (1) `urgent_possible` 8개 전부 포함. (2)
`urgent_possible`이 없는 6개 카테고리(`appetite_energy`,
`hospital_info`, `irrelevant`, `medication_response`, `pain_behavior`,
`pet_general`)에서 각 2개씩 12개 — 해당 카테고리에 `stable`/`worse`가
둘 다 있으면 1개씩(다양성 확보), 한 severity뿐이면 그중 2개.
`hospital_info`·`irrelevant`·`pet_general`은 전부 stable뿐이라
다양성을 줄 수 없었음. 총 20개.

**최종 표본 20개**:

| # | 이름 | 카테고리 | severity |
|---|---|---|---|
| 1 | followup_003 | symptom_change | urgent_possible |
| 2 | followup_004 | symptom_change | urgent_possible |
| 3 | followup_006 | symptom_change | urgent_possible |
| 4 | followup_007 | symptom_change | urgent_possible |
| 5 | followup_031 | stool_urine | urgent_possible |
| 6 | followup_033 | stool_urine | urgent_possible |
| 7 | followup_034 | stool_urine | urgent_possible |
| 8 | followup_035 | stool_urine | urgent_possible |
| 9 | followup_029 | appetite_energy | stable |
| 10 | followup_021 | appetite_energy | worse |
| 11 | followup_051 | hospital_info | stable |
| 12 | followup_053 | hospital_info | stable |
| 13 | followup_071 | irrelevant | stable |
| 14 | followup_072 | irrelevant | stable |
| 15 | followup_013 | medication_response | stable |
| 16 | followup_011 | medication_response | worse |
| 17 | followup_050 | pain_behavior | stable |
| 18 | followup_041 | pain_behavior | worse |
| 19 | followup_061 | pet_general | stable |
| 20 | followup_062 | pet_general | stable |

**사용자 검토 후 조정(2026-08-16)**: `hospital_info` 카테고리 11개 전체를
확인해보니 주차·운영시간 외에도 진료비·예약변경·처방전 재발급·다음
진료일·검사결과 확인·대기시간 등 다양한 유형이 있어, 12번을
`followup_052`(운영시간 — 11번 주차와 성격이 겹침)에서
`followup_053`(진료비 — 다른 유형)로 교체해 다양성을 확보함.

**severity 개념이 없는 카테고리**: `hospital_info`·`irrelevant`·
`pet_general` 3개 카테고리는 100개 전체에서 `worse`/`urgent_possible`
케이스가 원천적으로 0개(전부 stable). 병원 행정 문의·무관 잡담·일반
케어 질문은 성격상 "증상 악화" 개념이 적용되지 않는 카테고리로 보임 —
표본에 다양성이 없는 게 추출 방법의 한계가 아니라 카테고리 자체의
특성임을 기록해둠.

**남은 80개**: 라벨링하지 않음(Phase 9에서 데이터셋 전체 확장 시
재검토 여지).

### Followup 라벨링 완료 (표본 20/20, 2026-08-16)

`keyword_fallback()`은 Check 1·2가 실제로 쓰는 무료 결정론 함수라
Triage처럼 직접 실행해 시스템 계산 결과를 보여주며 진행. 표본 20개
전부 human_label=PASS(케이스 자체는 전부 타당) — 다만 이 중 4개
(followup_029, 013, 050, 062)에서 `keyword_fallback()`의 실제
오작동을 발견해 md 9번 섹션에 3가지 패턴(①긍정/부정 오판 ②매칭 누락
③무관 문의 과잉반응)으로 통합 기록. 케이스 자체를 고칠 문제가 아니라
시스템(채점 로직) 쪽 문제라 `expected_*` 값은 건드리지 않음.

| # | 이름 | 시스템 계산 vs 기대값 | 라벨 | 비고 |
|---|---|---|---|---|
| 1~8 | urgent_possible 8개 전부 | 전부 일치 | PASS | |
| 9 | followup_029 "밥을 다 먹었어요" | **불일치**(WORSE로 오판) | PASS | 패턴①, md 기록 |
| 10 | followup_021 | 일치 | PASS | |
| 11~14 | hospital_info×2, irrelevant×2 | 전부 일치 | PASS | |
| 15 | followup_013 "약 잘 먹고 있어요" | **불일치**(is_followup 누락) | PASS | 패턴②, md 기록 |
| 16 | followup_011 | 일치 | PASS | |
| 17 | followup_050 "활발해진 것 같아요" | **불일치**(is_followup 누락) | PASS | 패턴②, md 기록 |
| 18 | followup_041 | 일치 | PASS | |
| 19 | followup_061 | 일치 | PASS | |
| 20 | followup_062 "이 사료 괜찮은 건가요?" | **불일치**(과잉반응) | PASS | 패턴③, md 기록 |
