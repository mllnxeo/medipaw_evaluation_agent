"""ai/agents/eval_cases/*.json 골든 데이터셋 스키마 lint.

EVAL_AGENT_REDESIGN_PLAN.md 3번 섹션("유효성 검사")에 따라, 케이스 로딩
자체를 검증하는 게 아니라 파일에 손으로 채운 라벨 데이터 자체의 형식
오류를 잡는다. 라벨링 로직(평가 정확도)이 아니라 데이터 형식만 본다.

체크 항목:
  1. 각 케이스가 식별자 필드(name)를 갖는가
  2. human_label / human_note 키가 존재하는가 (값은 null이어도 됨 —
     아직 라벨링 전인 케이스는 에러가 아니라 "미라벨"로 집계)
  3. human_label 값이 null이 아니라면 PASS/FAIL/SKIP 중 하나인가

대상에서 제외: latency_test_cases.json — pass/fail 개념이 없는 순수
지연시간/토큰 벤치마크 데이터라 애초에 human_label을 붙일 대상이 아님
(EVAL_AGENT_REDESIGN_PLAN.md 9번 섹션 "Known Issues" 참고).

사용법: python backend/scripts/lint_eval_cases.py
종료 코드: 에러 0건이면 0, 있으면 1 (미라벨 케이스가 있는 것만으로는 실패하지 않음).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_EVAL_CASES_DIR = Path(__file__).resolve().parent.parent.parent / "ai" / "agents" / "eval_cases"
_VALID_LABELS = {"PASS", "FAIL", "SKIP"}

# latency_test_cases.json은 golden dataset이 아니라 벤치마크 픽스처라 제외.
_TARGET_FILES = [
    "triage_eval_cases.json",
    "chart_eval_cases.json",
    "schedule_eval_cases.json",
    "followup_eval_cases.json",
    "orchestrator_eval_cases.json",
    "reception_eval_cases.json",
]


def lint_file(path: Path) -> tuple[int, int, int, list[str]]:
    """(전체 케이스 수, 라벨링됨, 미라벨, 에러 메시지 목록) 반환."""
    cases = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    labeled = 0
    unlabeled = 0

    for i, case in enumerate(cases):
        ident = case.get("name") or f"[식별자 없음, index={i}]"

        if "name" not in case:
            errors.append(f"{path.name}#{i}: 식별자 필드(name) 없음")

        if "human_label" not in case:
            errors.append(f"{path.name}#{i} ({ident}): human_label 필드 없음")
            continue
        if "human_note" not in case:
            errors.append(f"{path.name}#{i} ({ident}): human_note 필드 없음")

        label = case["human_label"]
        if label is None:
            unlabeled += 1
        elif label in _VALID_LABELS:
            labeled += 1
        else:
            errors.append(
                f"{path.name}#{i} ({ident}): human_label 값이 잘못됨 "
                f"({label!r} — PASS/FAIL/SKIP/null 중 하나여야 함)"
            )

    return len(cases), labeled, unlabeled, errors


def main() -> int:
    total_errors: list[str] = []
    print(f"{'파일':<32} {'전체':>6} {'라벨링됨':>8} {'미라벨':>8}")
    print("-" * 60)

    for fname in _TARGET_FILES:
        path = _EVAL_CASES_DIR / fname
        if not path.exists():
            total_errors.append(f"{fname}: 파일 없음")
            continue
        total, labeled, unlabeled, errors = lint_file(path)
        print(f"{fname:<32} {total:>6} {labeled:>8} {unlabeled:>8}")
        total_errors.extend(errors)

    print("-" * 60)
    if total_errors:
        print(f"에러 {len(total_errors)}건:")
        for e in total_errors:
            print(f"  - {e}")
        return 1

    print("에러 없음 — 스키마 lint 통과 (미라벨 케이스는 에러 아님, Phase 2에서 라벨링 예정)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
