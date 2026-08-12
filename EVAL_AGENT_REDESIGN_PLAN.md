# 평가 에이전트 재설계 계획서

> 이 문서는 Claude Code가 순서대로 읽고 작업을 진행하기 위한 계획서입니다.
> 각 Phase는 의존관계 순으로 정렬되어 있으며, 임의로 순서를 건너뛰지 않습니다.

---

## 0. 배경 및 목표

### 배경

이 저장소는 2026년 5~6월 진행된 SKN25(SK네트웍스 Family AI 캠프) 최종 프로젝트
**MediPaw**(5인 팀 "Angel of Jazz")에서 파생되었다. MediPaw는 반려동물 진료 SaaS로,
팀 발표에서 5개 팀 중 1위를 기록했다. 본인(조민서)은 이 프로젝트에서 Backend
Leader이자 **평가 에이전트(Evaluation Agent) 담당**으로, 5개 AI 에이전트
(Triage/Schedule/Chart/Reception/경과필터)의 성능을 검증하는 하이브리드
(rule-based + LLM-as-judge) 평가 시스템을 처음부터 설계·구현했다.

프로젝트는 짧은 일정(약 5주) 안에 팀원 5명이 병렬로 여러 기능을 완성해야 하는
구조였고, 평가 에이전트는 그중에서도 참고할 선례가 특히 적은 영역이었다. 그
결과 다음과 같은 한계를 안은 채로 마무리되었다:

- 에이전트마다 판정 방식(1A~1E, 2A~2D 등)을 그때그때 다르게 설계해서, 전체
  구조를 한눈에 설명하기 어려웠다
- 통과/탈락 임계값(90%, 95% 등)이 실측 없이 정해진 숫자였다
- "rule과 LLM을 어떻게 하이브리드로 결합했는가"라는 질문에 일관된 답을 하기
  어려웠다
- LLM judge가 실제로 신뢰할 만한지 사람이 검증한 적이 없었다
- 프롬프트 인젝션, 접근 제어, 비용 통제 등 보안 관점의 고려가 거의 없었다

프로젝트 종료 후 약 한 달이 지난 시점에, 당시 급하게 만들었던 이 평가 시스템을
스스로 되짚어보다가 위 문제들을 인지했고, **혼자서 이를 실무 수준으로
재설계·재구현하며 평가 시스템 설계를 제대로 공부**하기로 했다.

### 목표

1. **설명 가능한 구조로 재설계** — 암묵적으로 반복해온 패턴(1차 매칭 → 실패시
   LLM 판단)을 3가지 체크 유형(Rule / Hybrid Gate / LLM Judge)으로 명시적으로
   정리하고, 모든 체크가 공통 스키마를 따르게 통일한다.
2. **근거 있는 임계값** — 감으로 정한 숫자가 아니라, 100개 규모의 golden
   dataset과 사람 라벨링, 통계적 신뢰구간 계산을 거쳐 임계값을 역산하는 절차를
   실제로 수행한다.
3. **LLM judge 검증** — 판정을 맡기기 전에 judge가 실제로 사람과 얼마나
   일치하는지 측정하고, 생성 모델과 분리한다.
4. **보안·운영 관점 보완** — 접근 제어, 프롬프트 인젝션 방어, 공급망 관리,
   비용 통제, 감사 로그 등 원래 프로젝트에서 다루지 못했던 부분을 추가한다.
5. **재발 방지** — 재작업 과정에서 발견한 실제 버그(집계 로직의 ERROR 무시
   등)를 재현 테스트와 함께 수정한다.
6. **누구에게나 설명 가능한 문서** — 이 문서(및 코드)를 팀원이나 면접관이
   읽었을 때, "왜 이렇게 설계했는가"에 대한 답이 항상 이 문서 안에 있도록
   만든다.

### 범위와 원칙

- 팀 원본 저장소(`mllnxeo/Medipaw`, `upstream`)는 건드리지 않는다. 이 작업은
  별도 저장소(`medipaw_evaluation_agent`, `minseo` 브랜치)에서 독립적으로
  진행한다.
- 팀이 공유하던 OpenAI 키 / AWS 인프라는 사용하지 않는다. 본인 개인 OpenAI 키
  + 로컬 Docker 환경만 사용한다.
- Golden dataset은 실사용자 데이터가 아닌 **합성(synthetic) 데이터**로 직접
  작성해, 개인정보 문제를 원천 차단한다.
- 이 작업은 운영 중인 서비스에 대한 실시간(online) 평가가 아니라, **오프라인
  회귀 테스트 체계를 정비하는 것**이 목표다. 실시간 프로덕션 모니터링은 이번
  범위 밖이다.

### 완료 정의

본 문서 14번 섹션("완료 정의")의 체크리스트를 모두 충족하면 이번 재작업을
완료로 간주한다.

---

## 1. 설계 원칙 — 3유형 통일

지금까지 5개 에이전트마다 제각각이던 판정 방식을 **딱 3가지 체크 유형**으로
통일한다.

| 유형 | 언제 쓰나 | 기존 코드 예시 |
|---|---|---|
| Rule | 결정론적으로 잴 수 있는 것 (DB값, 형식, 시간 겹침) | 근무시간 체크, SOAP 구조 존재 여부 |
| Hybrid Gate | 표현이 다양해서 rule만으론 놓치는 것 (1차 문자열매칭 → 실패한 것만 LLM) | 증상 키워드가 발화에 근거하는지 |
| LLM Judge | 애초에 정답이 없는 주관적 품질 | 대화 품질, 임상 품질 |

- 2개 계층(케이스 실시간 검증 `case_eval.py` / 오프라인 회귀 벤치마크
  `agent_bench.py`) 구조는 유지한다 — 이는 업계의 online/offline eval 구조와
  이미 일치한다.
- 모든 체크는 공통 스키마 `{item, type, status, detail}`로 반환한다.
  `status`는 `PASS / WARN / SKIPPED / ERROR`로 통일하고, 지금처럼
  `OK/ATTENTION/INFO` 등 어휘가 혼재하지 않게 한다.

```python
class CheckType(str, Enum):
    RULE = "rule"
    HYBRID_GATE = "hybrid_gate"
    LLM_JUDGE = "llm_judge"

class CheckResult(TypedDict):
    item: str
    type: CheckType
    status: Literal["PASS", "WARN", "SKIPPED", "ERROR"]
    detail: str
```

---

## 2. 기존 코드 버그 목록 (수정 대상)

- [ ] `case_eval.py`의 `_build_result` — `all_statuses`에서 `"WARN"`만
      확인하고 `"ERROR"`는 확인하지 않음. 검증 모듈이 예외로 죽어도
      `overall="OK"`로 표시되는 버그.
- [ ] `consistency_score` — 참조하는 체크 항목명(`"정합성"`)이 실제
      `validate_chart()`가 생성하는 항목명(`"SOAP 섹션 완전성"`, `"임상
      품질"`)과 불일치해, SOAP 구조 실패가 점수에 반영되지 않음.
- [ ] `_check_soap_sections` — A/P 항목이 문맥과 무관하게 지정된 단어 하나만
      있으면 통과 처리되어 게임 가능(gaming) 여지가 있음.
- [ ] `_is_phrase_assertive` / `_is_drug_prescribed` — 부정어 탐지가 고정
      20~25자 윈도우 방식이라 문장이 길어지면 오탐/누락 발생.
- [ ] `call_llm_structured()`(JSON 스키마 강제 출력)가 이미 구현되어 있는데
      실제 채점 함수들은 느슨한 `call_llm_json`을 사용 중.
- [ ] `/admin/eval/*`, `/admin/validation/run*` 엔드포인트에 rate limit이
      없음(로그인류 엔드포인트에만 적용되어 있음).
- [ ] `get_current_admin`에 권한 등급(role) 구분이 없어, 모든 admin 계정이
      비용이 나가는 평가 실행 권한을 동일하게 가짐.
- [ ] `ai/requirements-ai.txt`의 의존성이 상한 없이 열려 있음
      (`langfuse>=3.0.0` 등) — 재현성·공급망 리스크.

각 버그는 **수정 전에 재현 테스트를 먼저 작성**한다 (Phase 0 참고).

---

## 3. 골든 데이터셋 — 100개 구축

### 분배 (에이전트별)

| 에이전트 | 현재 케이스 수(추정) | 목표 |
|---|---|---|
| Triage | 15 | 40~50 |
| Chart | 19 | 30~40 |
| Schedule | 20 | 20~30 |
| Reception | 10 | 20 |
| 경과 필터 | 100 | 유지 |

### 케이스 스키마

```json
{
  "case_id": "triage_042",
  "category": "응급_호흡곤란",
  "difficulty": "hard",
  "input": { "messages": [] },
  "expected": { "urgency": "RED" },
  "human_label": "PASS",
  "human_note": "판단 근거 한 줄"
}
```

기존 `eval_cases/*.json`에는 `expected_*` 필드는 있지만 `human_label`,
`human_note`가 없다. 이 두 필드 추가가 이번 작업의 핵심 선행 작업이다 — 이게
있어야 judge 판정이 맞는지 틀린지 검증할 기준이 생긴다.

### 구성 원칙

- **출처**: 실사용자 데이터 없음 → **전부 합성(synthetic) 케이스로 직접
  작성**. 개인정보 문제를 원천 차단한다.
- **구성 비율**: 정상 케이스 60~70% + 경계값/예외 케이스 + **적대적
  (red-team) 케이스 10~15개** (판정 조작을 시도하는 발화를 자연스럽게 섞음).
- fail 케이스만 모으면 judge가 전부 "fail"이라고 찍어도 맞는 것처럼 보이는
  착시가 생기므로, pass 케이스도 반드시 충분히 섞는다.

### 라벨링 절차

1. 본인(또는 도메인 지식이 있는 사람)이 케이스를 직접 보고 pass/fail 판단 +
   근거 메모 작성.
2. 1~2주 뒤 라벨링한 케이스 중 10~15개를 라벨을 가린 채로 재채점해서, 자기
   자신과의 일치율로 **라벨 자체의 신뢰도**를 점검한다.

### 유효성 검사 (lint)

케이스 로딩 시 최소한의 스키마 검증을 자동으로 수행한다:
- 필수 필드(`case_id`, `human_label` 등) 존재 여부
- `human_label`이 `PASS` / `FAIL` / `SKIP` 중 하나인지
- 라벨링이 끝날 때마다 lint 스크립트를 1회 실행해, 데이터 자체의 오류와
  평가 로직의 오류를 구분한다.

---

## 4. 임계값 설정 방법론

### 원칙

임계값은 **먼저 정하지 않고, 측정한 뒤 역산**한다. 90%, 95% 같은 라운드
넘버를 먼저 정하고 거기 맞추는 방식은 쓰지 않는다.

### 절차

**1단계 — 기준선 측정 (반복 실행)**

```python
async def measure_baseline(agent: str, n_runs: int = 5):
    cases = load_golden_cases(agent)   # human_label 있는 케이스만
    results_per_run = []
    for run_i in range(n_runs):        # 비결정성 대응 — 5회 반복
        run_result = await run_eval(agent, cases)
        results_per_run.append(run_result)
    return aggregate(results_per_run, cases)
```
`temperature=0`이어도 LLM 출력이 100% 결정적이라는 보장이 없으므로, 최소
5회 반복 실행 후 집계한다.

**2단계 — 신뢰구간 계산**

```python
from scipy.stats import binomtest
result = binomtest(92, 100)  # 100개 중 92개 통과
ci_low, ci_high = result.proportion_ci(confidence_level=0.95, method="wilson")
```
표본이 작거나 비율이 0%/100%에 가까울 때(red flag recall 등) 일반
정규근사보다 정확한 `wilson` 방법을 사용한다. 점 추정치 하나만 기록하지
않고 **"92% (95% CI: 84~96%, n=100)"** 형태로 구간까지 함께 기록한다.

**3단계 — 유형별 임계값 결정 규칙**

| 구분 | 결정 방법 |
|---|---|
| Hard gate (red flag, 응급도) | 목표를 먼저 고정(recall 100%). 측정에서 미달이면 임계값을 낮추는 게 아니라 탐지 로직 자체를 100%에 도달할 때까지 고친다. |
| Soft gate (SOAP 문체, 대화품질 등) | 측정치가 곧 기준선. "신뢰구간 하한 − 여유분(margin) 5%p" 를 임계값으로 설정해 정상 변동을 오탐으로 잡지 않게 한다. |

**4단계 — 확정 전 안정성 재확인**

최소 2~3일에 걸쳐 다른 시간대에 재측정하고, 두 측정 결과의 신뢰구간이 겹칠
때만 확정한다.

**5단계 — 카테고리(슬라이스)별 분해**

전체 평균만 보지 않는다. `category` 필드로 나눠서 카테고리별 recall/precision을
따로 계산하고, 전체 평균이 기준을 넘어도 특정 카테고리가 미달이면 별도 표시한다.

**6단계 — Recall/Precision 균형**

Hard gate 항목도 recall 100%는 유지하되, **precision 하한선(예: 70%
이상)**을 함께 정한다. Recall만 극단적으로 올리면 오탐이 늘어 WARN이
남발되고, 결국 사람이 경고를 무시하는 "경고 피로(alert fatigue)"로 이어진다.

**7단계 — 버전 비교 시 통계적 유의성 확인**

프롬프트/모델을 바꾼 뒤 "92% → 94%"처럼 숫자가 바뀌었을 때, 표본이 100개면
2%p는 케이스 2개 차이라 우연일 수 있다. 단순 숫자 비교 대신 **페어드
비교**(어느 케이스가 새로 맞았고 어느 케이스가 새로 틀렸는지)로 실제
변화를 확인한다.

### 확정 결과 기록 형식

```yaml
triage:
  red_flag_recall:
    threshold: 1.0
    type: hard_gate
    rationale: "생명 관련 — 목표치 고정, 협상 불가"
  urgency_accuracy:
    threshold: 0.80
    type: soft_gate
    measured_baseline: 0.92
    measured_ci: [0.84, 0.96]
    measured_at: "2026-08-20"
    n_cases: 100
    n_runs: 5
```

---

## 5. LLM Judge 검증 및 분리

### 일치율 측정

- 사람 라벨 vs judge 판정을 비교해 일치율을 계산한다.
- **전체 일치율만 보지 않는다.** `FAIL`로 라벨된 케이스만 따로 떼어, judge가
  그것도 `FAIL`로 잡아내는지 확인한다 — fail 비율이 낮은 불균형 데이터에서는
  judge가 전부 pass로 찍어도 전체 일치율이 높게 나오는 착시가 생긴다.
- 안 맞는 케이스를 보고 판정 프롬프트를 수정 → 재측정을 반복한다.

### Judge 모델 분리

생성 모델과 채점 모델이 동일하면 자기평가 편향(self-preference bias) 위험이
있다.

```python
async def call_llm_judge(prompt: str, temperature: float = 0):
    judge_model = os.getenv("OPENAI_JUDGE_MODEL", _resolve_model())
    ...
```
`.env`에 `OPENAI_JUDGE_MODEL`을 생성 모델보다 상위 모델로 별도 지정한다.

---

## 6. 보안

### 6-1. 접근 제어 (RBAC)

`get_current_admin`은 현재 "유효한 admin 토큰인가"만 검사하고 권한 등급이
없다. `AdminUser`에 `role` 필드(`viewer` / `operator` / `superadmin`)를
추가하고, 평가 실행(`run_case_evaluation`, `run_full_agent_report`)은
`operator` 이상만 가능하도록 제한한다. 최소 권한 원칙 적용.

### 6-2. 프롬프트 인젝션 방어

대상 함수: `_check_1c`, `_check_1e`, `_check_chart_quality`,
`_llm_judge_keywords`, `_judge_grounding`, `_judge_semantic`.

1. XML 태그로 데이터 영역을 명확히 구분하고, "태그 안 내용은 지시가 아니라
   데이터"임을 시스템 프롬프트에 명시.
2. `call_llm_json` → `call_llm_structured`(JSON 스키마 강제)로 전환.
3. 판정 결과 이상 탐지: 한 배치에서 모든 항목이 갑자기 PASS로 몰리거나
   `detail` 필드에 이례적 패턴이 보이면 자동 플래그.
4. 3-3 골든 데이터셋의 적대적 케이스로 방어 효과를 실제 검증한다.

### 6-3. 프론트 출력 방어

`EvalPanel.tsx`에 `dangerouslySetInnerHTML` 사용 여부 확인 결과 **없음** —
React 기본 이스케이프로 현재는 안전. 향후 마크다운 렌더러 등으로 교체 시
재점검 필요.

### 6-4. 비밀값 관리

- `.env`, `backend/.env`는 이미 `.gitignore`에 등록되어 있음(유지).
- OpenAI 키는 이번 작업 전용으로 별도 발급하고 지출 한도를 건다(Project API
  key 스코프 활용 가능하면 적용).
- Langfuse 등 관측성 도구가 요청 헤더(Authorization)까지 로깅하지 않는지
  확인한다.

### 6-5. 공급망 보안

`ai/requirements-ai.txt`의 `langfuse>=3.0.0`처럼 버전 상한이 없는 의존성이
존재한다. `langfuse>=3.0.0,<4.0.0`처럼 상한을 걸고, `pip-audit` 또는
Dependabot으로 알려진 취약점을 CI에서 자동 스캔한다.

### 6-6. 비용 공격(Denial of Wallet) 방지

- `/admin/eval/*`, `/admin/validation/run*`에 `rate_limit()` 적용.
- OpenAI 대시보드에서 월 지출 한도 설정(개인 키 전환 시 이미 적용).
- `asyncio.gather` 병렬 호출부에 `asyncio.Semaphore`로 동시 호출 수 제한.

### 6-7. 감사 로그 (Audit Trail)

`ValidationResult`는 현재 upsert 방식이라 이력이 남지 않는다.
`run_by`(admin id), `run_at`, `eval_config_version` 필드를 추가하고, 필요 시
덮어쓰기 대신 이력 테이블로 전환을 고려한다.

---

## 7. 재현성 및 버전관리

- **모델 버전 고정**: `OPENAI_MODEL` 변경 시 평가 결과 자체가 바뀔 수 있으므로,
  모델 업그레이드 전 golden dataset을 새 모델로 재실행해 기존 임계값의 유효성을
  재확인한다.
- **비결정성 처리**: hard gate 항목은 3회 이상 반복 실행 후 다수결로 판정하는
  것을 고려한다.
- **데이터셋 버전관리**: `eval_cases/*.json` 변경은 git 커밋으로 이력을
  남기고, 임계값 재설정 시 어느 데이터셋 버전(커밋 해시) 기준인지 함께 기록한다.

---

## 8. 컴플라이언스

현재는 합성 데이터만 사용하므로 즉각적 문제는 없다. 다만 도메인 특성상(보호자
개인정보 + 동물 건강정보) 향후 실사용자 데이터를 사용하게 될 경우 개인정보보호법상
민감정보 처리 이슈가 발생할 수 있음을 명시해둔다 — 실데이터 도입 시 마스킹 및
동의 절차 필요.

---

## 9. 한계 명시 (Known Limitations)

- 현재 평가 체계는 orchestrator의 **라우팅 결과만** 확인하며, 그 판단에
  이르는 경로(trajectory)는 평가하지 않는다.
- LLM judge가 생성 모델과 동일 계열이라, 모델을 분리해도 완전한 독립 검증은
  아니다.
- 100개 규모의 데이터셋은 통계적으로 여전히 작은 표본이며, 희귀 케이스
  조합까지 커버하지 못할 수 있다.

---

## 10. 사람 개입 경로 (Escalation)

- Hard gate 위반 시 최소한 로그 레벨을 `ERROR`로 남긴다.
- `ValidationResult`에 `reviewed_by`, `resolved_at` 필드를 추가해, 경고가
  실제로 검토·해소되었는지 추적 가능하게 한다(향후 개선 방향으로 명시, 이번
  범위에서 전체 구현은 선택).

---

## 11. 테스트 및 CI

- 현재 평가 코드(`_build_result`, `_calc_completeness` 등) 자체에 단위
  테스트가 없다. **버그 재현 테스트를 먼저 작성한 뒤 수정**하는 순서를 지킨다
  (Phase 0).
- CI(`ci.yml`)에는 **비용이 없는 rule 체크**(SOAP 구조, 형식 유효성 등)만
  우선 연결한다. LLM 호출이 있는 체크는 별도 nightly 잡으로 분리한다.
- 코드 변경 시 golden dataset을 재실행해 기존 베이스라인 대비 하락하면
  회귀로 처리한다.

---

## 12. 스키마 통일 및 프론트 반영

- `case_eval.py`, `agent_bench.py` 양쪽을 공통 `CheckResult` 스키마로 통일.
- `EvalPanel.tsx`의 체크 항목마다 유형 태그(`rule` / `hybrid_gate` /
  `llm_judge`)를 표시.
- "전체 성능" 탭 상단에 구조 다이어그램(3유형 → 공통 스키마 → 집계 → 두
  리포트)을 삽입해, 처음 보는 사람도 전체 그림을 바로 파악할 수 있게 한다.

---

## 13. 실행 순서 (Phase)

각 Phase는 시작 조건과 완료 조건을 명시한다. 순서를 건너뛰지 않는다.

| Phase | 내용 | 시작 조건 | 완료 조건 |
|---|---|---|---|
| 0 | 버그 재현 테스트 작성 → 수정 | 2번 섹션 버그 목록 확정 | 2번 섹션 모든 항목 테스트 통과 |
| 1 | 데이터셋 스키마 확장 (`human_label`, `human_note`) | Phase 0 완료 | 모든 `eval_cases/*.json`에 필드 존재 + lint 통과 |
| 2 | 1차 20~30개 합성 케이스 작성 + 라벨링 | Phase 1 완료 | 에이전트별 최소 20개 라벨링 완료 |
| 3 | judge 일치율 측정 스크립트 작성/실행 | Phase 2 완료 | 일치율 수치 산출 + FAIL 케이스 recall 별도 산출 |
| 4 | 판정 프롬프트 보정 (반복) | Phase 3 완료 | 일치율이 목표 수준에서 안정화 |
| 5 | 공통 `CheckResult` 스키마 설계 + 백엔드 반영 + 프론트 호환 | Phase 4 완료 | 6개 탭 기존과 동일하게 렌더링 확인 |
| 6 | hard/soft gate 구분 + `eval_config.yaml` 분리 | Phase 5 완료 | 4번 섹션 절차대로 임계값 확정 및 기록 |
| 7 | judge 모델 분리 + 구조화 출력 전환 + 인젝션 방어 | Phase 6 완료 | 적대적 케이스 방어 검증 통과 |
| 8 | rate limit / 동시성 제한 / RBAC | Phase 7 완료 | 6번 섹션 항목 전부 반영 |
| 9 | 데이터셋 100개로 확장 (+ 적대적 케이스 10~15개) | Phase 8 완료 | 3번 섹션 목표 수량 도달 |
| 10 | CI 연동 (rule 체크 우선, LLM 체크 nightly) | Phase 9 완료 | CI에서 rule 체크 최소 3개 자동 실행 확인 |

---

## 14. 완료 정의 (Definition of Done)

- [ ] 5개 에이전트 전부 공통 스키마(`CheckResult`) 반환
- [ ] Hard gate 항목 recall 100% 확인됨 (측정 근거 기록 포함)
- [ ] Judge 판정-사람 라벨 일치율 측정 완료 + 기록 남김
- [ ] 임계값 전부 `eval_config.yaml`로 이동, 근거(측정치·신뢰구간·커밋) 기록
- [ ] CI에 rule 체크 최소 3개 이상 자동 실행
- [ ] 기존 프론트 6개 탭 정상 렌더링 유지
- [ ] 2번 섹션의 버그 전부 재현 테스트와 함께 수정 완료
- [ ] RBAC, rate limit, judge 모델 분리 반영 완료

---

## 부록

### A. 시각화 (md 범위 밖, 참고용)

평가 결과 시각화는 이 리팩터링과 별도로 진행한다.
- **Tableau Public**(무료) — PostgreSQL 직접 연결 불가, CSV로 내보내 사용.
  공개 워크북이므로 집계된 수치만 업로드하고 원본 대화 데이터는 올리지 않는다.
- **Tableau Desktop**(학생 라이선스 확인 시) — PostgreSQL 직접 연결 가능.
- 추천 시각화: 에이전트별/체크유형별 pass율, 임계값 대비 실측치 추이,
  hard/soft gate 위반 건수, 사람 라벨 vs judge 판정 confusion matrix.

### B. 레포 히스토리 관련 주의사항

`medipaw_evaluation_agent` 저장소는 `Medipaw`를 fork하며 팀 전체 커밋
히스토리를 그대로 포함하고 있다. 현재 Private로 유지 중이면 문제없으나,
추후 Public 전환 또는 포트폴리오 공개 시:
- 팀원들에게 사전 동의를 구할 것
- 필요 시 `git checkout --orphan`으로 히스토리를 정리한 별도 공개용
  스냅샷 브랜치를 만들 것

### C. 비용 예산 개요 (참고치, Phase 실행 전 재산정 권장)

| Phase | 대략적 LLM 호출 규모 |
|---|---|
| 3 (judge 일치율 측정) | 케이스 수 × 2~3회 반복 |
| 4 (프롬프트 보정) | 반복 횟수 × 케이스 수 (여러 차례) |
| 6 (임계값 확정 측정) | 케이스 수 × 5회 반복 × 2~3일 |
| 9 (100개 확장 후 재측정) | 100 × 5회 반복 |

### D. 용어집

- **Golden dataset**: 정답(사람 라벨)이 붙은 고정 테스트 케이스 모음.
- **Hard gate**: 기준 미달 시 배포 자체를 막는 체크(생명·안전 직결 항목).
- **Soft gate**: 기준 미달 시 경고만 띄우고 배포는 진행하는 체크.
- **Judge calibration**: LLM judge의 판정을 사람 라벨과 비교해 프롬프트를
  보정하는 과정.
- **Hybrid gate**: 1차로 결정론적 매칭을 시도하고, 실패한 것만 LLM에 넘겨
  의미 판단을 받는 비용 절감형 패턴.

---

## Changelog

| 날짜 | 내용 |
|---|---|
| 2026-08-12 | 최초 작성 |
