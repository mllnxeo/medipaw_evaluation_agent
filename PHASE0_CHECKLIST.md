# Phase 진행 체크리스트

> `EVAL_AGENT_REDESIGN_PLAN.md`가 "무엇을, 왜 하기로 했는가"를 담는
> 문서라면, 이 파일은 "Phase별로 실제로 무엇을 했는가"를 담는 실행 기록이다.
> 각 Phase가 끝날 때마다 새 섹션을 추가해 계속 이어 쓴다 — 나중에 전체
> 히스토리를 한눈에 훑어볼 수 있게 유지하는 것이 목적이다. 계획과 실제
> 구현이 달라진 지점은 반드시 이유와 함께 기록한다.

---

## Phase 0 — 버그 재현 테스트 작성 → 수정

**기간**: 2026-08-12
**범위 확정**: `EVAL_AGENT_REDESIGN_PLAN.md` 2번 섹션의 버그 8개 중 순수 로직
버그 1~4번만 Phase 0에서 다룸. 5~8번(구조화 출력 전환, rate limit, RBAC,
의존성 버전 상한)은 13번 섹션 Phase 표에서 이미 각각 Phase 7·8에 배정돼
있어, 그쪽에서 본격적으로 다루기로 함(사용자 승인).

### 사전 작업

- `ai/agents/evaluation/case_eval.py`, `ai/agents/evaluation/agent_bench.py`,
  `ai/llm.py`를 읽고 8개 버그를 실제 코드에서 확인.
- 로컬 Python(3.12)엔 pytest·sqlalchemy 등 의존성이 없어, 이미 떠 있던
  `docker-backend-1` 컨테이너(`/app` = PYTHONPATH, ai/backend 둘 다 마운트됨)에
  `pytest>=8,<9`, `pytest-asyncio`를 추가 설치해 그 안에서 테스트 실행
  (CI(`ci.yml`)가 쓰는 것과 동일한 조합).

### 항목별 기록

#### 1. `_build_result` — ERROR 무시 버그

- **한 일**: `case_eval.py`의 `_build_result()` 함수. `overall` 판정식을
  `"ATTENTION" if "WARN" in all_statuses else "OK"` →
  `"ATTENTION" if ("WARN" in all_statuses or "ERROR" in all_statuses) else "OK"`로 수정.
- **계획과의 차이**: 계획 승인 시엔 `overall`에 `"ERROR"`라는 새 값을
  추가하기로 했었음. 구현 직전 `EvalPanel.tsx`를 확인하니
  `OverallStatus = "OK" | "ATTENTION" | "SKIPPED"` 타입과 `passCount`/
  `warnCount` 집계가 `"ERROR"`를 모르는 값으로 취급해, 도입 시 대시보드
  집계에서 해당 행이 조용히 누락되는 프론트 회귀가 생김을 발견. 이걸 먼저
  사용자에게 확인받지 않고 "ATTENTION으로 합치는" 쪽으로 바꿔서 구현한 뒤
  사후에 설명한 것 자체가 이번 Phase에서 지적받은 프로세스 문제였음(아래
  "이번 Phase에서 배운 것" 참고). 이후 사용자에게 old/new 비교와 트레이드오프를
  보여주고 "ATTENTION으로 합치는" 방향을 그대로 승인받음(2026-08-12).
- **재현 테스트**: `test_build_result_does_not_report_ok_when_a_module_errors`
  - OLD: triage 모듈이 ERROR 체크만 가진 입력 → `overall = "OK"` (버그 재현)
  - NEW: 같은 입력 → `overall = "ATTENTION"`
- **다음 Phase로 넘긴 것**: WARN으로 인한 ATTENTION과 ERROR로 인한 ATTENTION을
  집계 화면에서 구분하는 것은 프론트 타입까지 포함한 공통 `CheckResult` 스키마
  통일이 필요 — Phase 5.

#### 2. `consistency_score` — 항목명 불일치로 SOAP 실패가 반영 안 됨

- **한 일**: `_build_result()`의 `consistency_score` 계산부. 매칭 대상 항목명에
  `"SOAP 섹션 완전성"`을 추가하고, 계산 방식을 "마지막으로 매칭된 항목의
  PASS/WARN"에서 "관련 항목(`정합성`/`SOAP 섹션 완전성`/`임상 품질`)이 전부
  `PASS`일 때만 10.0, 하나라도 `WARN`이면 `None`"으로 변경.
- **계획과의 차이**: 없음. 애초에 "감점 폭을 임의로 정하지 말고, WARN이 하나라도
  있으면 None을 반환"하는 방향으로 사용자가 직접 정정해서 승인한 계획을 그대로
  구현.
- **재현 테스트**:
  - `test_consistency_score_is_none_when_soap_section_check_warns`
    - OLD: SOAP만 WARN, 임상품질 PASS → `consistency_score = 10.0` (버그 재현 —
      SOAP 실패가 전혀 반영 안 됨)
    - NEW: 같은 입력 → `consistency_score = None`
  - `test_consistency_score_is_10_when_both_chart_checks_pass` — 둘 다 PASS →
    10.0 유지 확인(회귀 없음)
  - 추가로 수동 확인(테스트 파일엔 없음, 대화 중 직접 실행): 둘 다 WARN → None,
    임상품질만 WARN → None — 모두 일관되게 동작.
- **다음 Phase로 넘긴 것**: `consistency_score`의 실제 감점 폭(WARN일 때 몇 점을
  줄 것인가) 설계는 Phase 6에서 golden dataset 실측 기반으로 진행.

#### 3. `_check_soap_sections` — A/P 게이밍 가능

- **한 일**: `case_eval.py`에 `_A_KEYWORDS`/`_P_KEYWORDS`/`_SOAP_NEG_KW`를
  모듈 레벨 상수로 두고, 로직을 `_soap_section_issues(soap) -> list[str]`로
  추출. A/P 키워드 매칭에 문장 단위 부정어 인지(`keyword_in_context`)를 적용해
  `"검사는 필요 없습니다"`처럼 부정 문맥에 등장한 키워드는 요건 충족으로
  인정하지 않게 함. `_check_soap_sections()`는 이제 `_soap_section_issues()`를
  호출하는 얇은 wrapper.
- **계획과의 차이**: 구현 중 `agent_bench.py`의 `run_chart_eval()` Check 1에
  동일한 SOAP 체크 로직(같은 `_A_KEYWORDS`/`_P_KEYWORDS`, 부정어 처리 없음)이
  완전히 복붙되어 있는 걸 추가로 발견(계획 문서엔 없던 사실). 한쪽만 고치면
  다른 쪽에 같은 버그가 그대로 남기 때문에, `agent_bench.py`가
  `case_eval._soap_section_issues`를 import해서 재사용하도록 통합 — 이건
  버그 수정을 완전하게 하기 위해 필요한 조치라 별도 확인 없이 진행함(리팩터링
  범위가 "같은 버그의 두 번째 발생 지점 제거"로 한정돼 있어 계획 취지에서
  벗어나지 않는다고 판단).
- **재현 테스트**:
  - `test_check_soap_sections_rejects_negated_p_keyword`
    - OLD 로직(수동 실행): `{"A": "감별", "P": "검사는 필요 없습니다"}` → 이슈
      없음(PASS, 버그 재현)
    - NEW: 같은 입력 → `status = "WARN"`, `"P"` 이슈 포함
  - `test_check_soap_sections_passes_when_p_keyword_not_negated` — 부정되지
    않은 정상 키워드는 여전히 PASS (회귀 없음 확인)
- **다음 Phase로 넘긴 것**: 없음 — 이 항목은 Phase 0 안에서 완결.

#### 4. `_is_phrase_assertive` / `_is_drug_prescribed` — 고정 윈도우 부정어 탐지

- **한 일**: `ai/agents/evaluation/text_match.py`를 새로 만들어
  `keyword_in_context(text, keyword, negations)` 공유 헬퍼 구현 — 문장 단위로
  쪼갠 뒤, 키워드가 등장한 문장 안에 부정어가 있는지(순서·거리 무관) 판단.
  `agent_bench.py`의 `_is_phrase_assertive`/`_is_drug_prescribed`가 이 헬퍼를
  쓰도록 재작성.
- **계획과의 차이**: 두 함수가 원래 각각 `run_chart_eval()`/`run_schedule_eval()`
  내부의 지역 함수였다는 사실은 계획 문서에 없었음(그래서 애초엔 단위 테스트로
  직접 import가 불가능했다 — 첫 테스트 실행 시 `ImportError`로 발견). 버그를
  고치는 김에 모듈 레벨로 옮겨 재사용·테스트 가능하게 함. 부정어 키워드 목록
  (`_PHRASE_NEG_KW`, `_DRUG_NEG_KW`) 자체는 바꾸지 않음 — 매칭 알고리즘(고정
  윈도우 → 문장 단위)만 교체.
- **재현 테스트** (아래 문자열은 구현 전 실제 원본 함수로 직접 실행해 버그를
  먼저 확인한 뒤 작성):
  - `test_is_phrase_assertive_detects_negation_before_keyword`
    - 입력: `"확정 진단을 내리는 것은 어렵지만, 파보바이러스 장염으로 최종 진단합니다"`
    - OLD: `True`(단정으로 오판, 버그 — 부정어 "어렵"이 키워드보다 앞이라
      forward-only 윈도우가 못 잡음) / NEW: `False`
  - `test_is_phrase_assertive_detects_negation_beyond_fixed_window`
    - 부정어("아님")가 키워드 뒤 30자 윈도우 밖에 있는 긴 문장 →
      OLD: `True`(버그) / NEW: `False`
  - `test_is_phrase_assertive_still_true_when_genuinely_assertive` — 정상적으로
    단정하는 문장은 여전히 `True` (회귀 없음)
  - `test_is_drug_prescribed_detects_negation_before_pattern`
    - 입력: `"절대 투여 금지 사항이 있으니 참고하시고, 항생제 반응을 지켜봐 주세요"`
    - OLD: `True`(버그) / NEW: `False`
  - `test_is_drug_prescribed_still_true_when_genuinely_prescribed` — 정상
    처방 문구는 여전히 `True` (회귀 없음)
- **다음 Phase로 넘긴 것**: 없음 — 이 항목은 Phase 0 안에서 완결. (완벽한
  자연어 이해는 아니라는 한계는 `text_match.py` 상단 docstring에 명시.)

### 변경 파일

| 파일 | 종류 | 내용 |
|---|---|---|
| `ai/agents/evaluation/text_match.py` | 신규 | `keyword_in_context`, `split_sentences` |
| `ai/agents/evaluation/case_eval.py` | 수정 | `_build_result`(버그 1·2), `_soap_section_issues`/`_check_soap_sections`(버그 3) |
| `ai/agents/evaluation/agent_bench.py` | 수정 | `_is_phrase_assertive`/`_is_drug_prescribed` 모듈 레벨로 이동 + 문장 단위 매칭 전환(버그 4), `run_chart_eval`의 SOAP 체크 중복 제거(버그 3) |
| `backend/tests/evaluation/test_case_eval_bugs.py` | 신규 | 버그 1~4 재현 테스트 10개 |
| `EVAL_AGENT_REDESIGN_PLAN.md` | 수정 | 2번 섹션 4개 항목 체크 + "고친 부분" 기록, 13번 섹션 Phase 0 행 범위 명시, 14번 섹션 `consistency_score` 임시 동작 노트 |
| `PHASE0_CHECKLIST.md` | 신규 | 이 파일 |

### 테스트 결과

- `docker exec docker-backend-1 python -m pytest tests/evaluation/test_case_eval_bugs.py -v` → **10 passed**
- `docker exec docker-backend-1 python -m pytest -m "not live" -q` (전체 스위트, `live` 마커 제외 — CI와 동일 조건) → **136 passed, 6 deselected**, 회귀 없음

### 이번 Phase에서 배운 것 (프로세스)

- 계획에서 벗어나는 구현 판단(예: `overall="ERROR"` 추가 대신 기존
  `"ATTENTION"`에 합치기)이 필요할 때, **구현하고 나서 사후에 설명하는 방식은
  안 됨** — 반드시 구현하기 *전에* 사용자에게 먼저 확인받아야 함. 버그 1
  수정에서 이 순서를 지키지 않아 사용자가 직접 지적함. 이후 Phase부터는
  이 원칙을 지킴.

### 아직 확인 안 된 것 / 사용자가 확인할 것

- [ ] 이 문서(`PHASE0_CHECKLIST.md`) 및 `EVAL_AGENT_REDESIGN_PLAN.md` 수정
      내용 최종 확인
- [ ] 위 변경사항 커밋 여부 확인 (git 저장소: `Medipaw`, branch `minseo`,
      현재 미커밋 상태)
- [ ] Phase 0 완료 조건("2번 섹션 1~4번 재현 테스트 통과") 충족 — 근거는
      위 "테스트 결과" 참고
