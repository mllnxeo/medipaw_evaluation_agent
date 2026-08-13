# Phase 진행 체크리스트 (계속)

> `PHASE0_CHECKLIST.md`에서 이어지는 실행 기록. 형식은 동일 — 각 Phase가
> 끝날 때마다 새 파일 대신 이 시리즈에 섹션을 추가해 계속 이어 쓴다.

---

## Phase 1 — 데이터셋 스키마 확장 (`human_label`, `human_note`)

**기간**: 2026-08-13

### 시작 전 확인한 것 (계획-실제 mismatch)

계획 승인 전 `eval_cases/*.json` 6개 파일의 실제 구조를 확인한 결과, md
3번 섹션과 다른 점 여러 개를 발견해 진행 전 사용자에게 확인받음:

- md의 예시 스키마는 식별자로 `case_id`를 쓰지만, 실제 파일은 전부 `name`을
  씀(`followup_eval_cases.json`은 그마저 없음). → **식별자 필드명은
  바꾸지 않고 기존 `name`을 그대로 유지**하기로 결정.
- `orchestrator_eval_cases.json`(23개)이 3번 섹션 표에 아예 없었음. →
  Phase 1 완료 조건("모든 eval_cases/*.json")이 문자 그대로 이 파일도
  포함하므로 lint 대상에 넣고, 표에도 추가(아래 "표에 추가한 것" 참고).
- `latency_test_cases.json`은 pass/fail 개념이 없는 순수 지연시간/토큰
  벤치마크 데이터라 golden dataset 범위 밖으로 판단, lint 대상에서 제외.
  이 파일의 한글 텍스트가 인코딩 깨짐 상태인 것도 이때 발견 —
  `EVAL_AGENT_REDESIGN_PLAN.md` 9번 섹션 "Known Issues"에 기록, Phase 1
  범위 밖이라 수정하지 않음.
- **Reception은 애초에 JSON 파일이 없었음** — `agent_bench.py`의
  `run_reception_eval()` 내부 `_TOOL_CASES` 하드코딩 튜플 10개로만
  존재. 사용자에게 "JSON 파일로 분리할지 vs 이번엔 손대지 않을지" 확인받고,
  분리하는 쪽으로 결정(아래 참고).
- Triage의 md 표기(15, "추정")가 실제(40)와 크게 다름을 발견 — 실측치로
  정정.

### 표에 추가한 것 — Orchestrator

3번 섹션 "분배(에이전트별)" 표에 없던 Orchestrator를 6번째 행으로 추가.
목표치는 사용자와 논의해 **20~30**으로 결정(Reception보다는 phase×flow
조합이 다양해 여유를 두되, Triage/Chart처럼 임상 카테고리 세분화가
필요한 성격은 아니라 Schedule과 동일 구간). 근거는 md 표 아래 각주로
기록함. 원래 왜 표에서 빠져 있었는지는 확인할 수 없는 추측이라 md에는
적지 않음(사용자 지시).

### 한 일

1. **6개 파일에 `human_label`/`human_note` 필드 추가** —
   `triage_eval_cases.json`(40), `chart_eval_cases.json`(19),
   `schedule_eval_cases.json`(20), `followup_eval_cases.json`(100),
   `orchestrator_eval_cases.json`(23), `reception_eval_cases.json`(10,
   신규) — 총 212개 케이스. 값은 전부 `null`(아직 미라벨 — 실제 라벨링은
   Phase 2). 기존 손으로 짠 포맷(한 줄/여러 줄 혼재)을 그대로 보존하기
   위해 `json.dump` 전체 재포맷 대신, stdlib `json.JSONDecoder.raw_decode`로
   각 케이스 객체의 정확한 시작/끝 오프셋만 찾아 원본 텍스트를 부분
   수정하는 스크립트를 작성해 적용. 적용 후 원본 대비 "필드 추가 외
   나머지 값이 100% 동일한지" Python으로 재검증함.
2. **`followup_eval_cases.json`에 식별자 추가** — 계획에 없던 작업. 이
   파일만 식별자 필드가 전혀 없어 lint의 "식별자 존재 확인"을 만족할 수
   없었음. `"name": "followup_001"` ~ `"followup_100"` 순번으로 추가
   (다른 파일과 필드명 통일).
3. **Reception 분리** — 계획에 없던 작업(사용자 승인 후 진행).
   - `ai/agents/eval_cases/reception_eval_cases.json` 신규 생성 —
     `agent_bench.py`의 `_TOOL_CASES` 튜플 10개를
     `{"name", "message", "expected_tool", "human_label": null, "human_note": null}`
     구조로 옮김(내용은 1:1 동일, 튜플 순서·값 변경 없음).
   - `agent_bench.py`: `_load_reception_cases()` 로더 함수 신규(다른
     `_load_*_cases()`와 동일 패턴). `run_reception_eval(db)` →
     `run_reception_eval(db, test_cases=None)`로 시그니처 변경, 하드코딩된
     `_TOOL_CASES` 순회 대신 `test_cases or _load_reception_cases()`로
     로드하도록 수정. 다른 `run_*_eval` 함수들과 파라미터 패턴 통일.
4. **`backend/scripts/lint_eval_cases.py` 신규** — 6개 파일을 순회하며
   식별자·`human_label`·`human_note` 필드 존재 확인, `human_label`이
   `null`이 아니면 `PASS`/`FAIL`/`SKIP` 중 하나인지 검증. `null`(미라벨)은
   에러가 아니라 별도 집계.
5. **로더 검증 테스트 추가** — `backend/tests/evaluation/test_eval_cases_schema.py`.
   `lint_eval_cases.py`는 JSON을 직접 파싱해 형식만 보지만, 이 테스트는
   `agent_bench.py`가 실제로 쓰는 6개 로더 함수(`_load_triage_cases`,
   `_load_chart_cases`, `_load_schedule_cases`, `_load_followup_cases`,
   `_load_orchestrator_cases`, `_load_reception_cases`)를 직접 호출해
   케이스 수·필드 존재를 검증 — 파일 포맷과 프로덕션 로드 경로 양쪽을
   확인하기 위해 사용자가 명시적으로 범위를 넓혀달라고 요청함. 처음엔
   6개 로더를 for 루프로 합쳐 검증(테스트 노드 2개)했으나, 사용자가
   "특정 파일 하나가 깨졌을 때 pytest 결과만 보고 바로 알 수 있는가"를
   묻고 확인해보니 루프 구조에서는 (a) 노드 이름만으로는 파일 구분이
   안 되고 (b) 여러 파일이 동시에 깨져도 루프상 첫 번째 실패에서
   멈춰 나머지가 가려지는 문제가 있어, `@pytest.mark.parametrize`로
   로더별 개별 테스트 노드(`test_...[_load_chart_cases]` 등)로
   리팩터함 — 이제 여러 파일이 동시에 깨져도 전부 각자 실패로 표시됨.

### 변경 파일

| 파일 | 종류 | 내용 |
|---|---|---|
| `ai/agents/eval_cases/triage_eval_cases.json` | 수정 | human_label/human_note 추가 |
| `ai/agents/eval_cases/chart_eval_cases.json` | 수정 | 〃 |
| `ai/agents/eval_cases/schedule_eval_cases.json` | 수정 | 〃 |
| `ai/agents/eval_cases/orchestrator_eval_cases.json` | 수정 | 〃 |
| `ai/agents/eval_cases/followup_eval_cases.json` | 수정 | human_label/human_note + name 식별자 추가 |
| `ai/agents/eval_cases/reception_eval_cases.json` | 신규 | `_TOOL_CASES`에서 분리 |
| `ai/agents/evaluation/agent_bench.py` | 수정 | `_load_reception_cases` 추가, `run_reception_eval` 시그니처 변경 |
| `backend/scripts/lint_eval_cases.py` | 신규 | 스키마 lint |
| `backend/tests/evaluation/test_eval_cases_schema.py` | 신규 | 로더별 parametrize 검증 테스트 13개 |
| `EVAL_AGENT_REDESIGN_PLAN.md` | 수정 | 3번 섹션(Orchestrator 행 추가, Triage 실측 정정), 9번 섹션(latency 인코딩 이슈), 13번 섹션(Phase 1 완료 조건 구체화), Changelog |
| `PHASE1_CHECKLIST.md` | 신규 | 이 파일 |

### 테스트 결과

- `python backend/scripts/lint_eval_cases.py` → **에러 0건**, 6개 파일 212개
  케이스 전부 필드 존재 확인(전부 미라벨 상태, 예상대로 — Phase 2에서 라벨링 예정)
- `pytest tests/evaluation/test_eval_cases_schema.py -v` → **13 passed**
  (parametrize 리팩터 후 — 로더 6개 × 검증 2종 + reception 전용 1개), 로더별
  개별 노드(`test_loader_returns_expected_case_count[_load_chart_cases]` 등)로
  분리되어 파일별 실패가 각각 표시됨
- `pytest -m "not live" -q` (전체 스위트) → **149 passed, 6 deselected**
  (Phase 0의 136 + 이번 13), 회귀 없음

### 다음 Phase로 넘긴 것

- 실제 라벨링(pass/fail 판단 + 근거 메모) — Phase 2
- 케이스 수를 목표치까지 늘리는 것(Chart 19→30~40, Reception 10→20 등) —
  Phase 2/Phase 9
- `latency_test_cases.json`의 한글 인코딩 복구 — 범위 밖으로 명시(md 9번
  섹션 Known Issues), 담당 Phase 미배정

### 아직 확인 안 된 것 / 사용자가 확인할 것

- [ ] 이 문서 및 `EVAL_AGENT_REDESIGN_PLAN.md` 수정 내용 최종 확인
- [ ] 커밋 여부 확인
