"""Phase 3 Triage 조작 시도 — 특정 기준만 겨냥해 망가뜨린 대화로 judge 변별력 테스트.

생성 LLM 호출 없이 대화 텍스트를 직접 작성해 _check_1e에 바로 넣는다.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "/app")

from ai.agents.evaluation.case_eval import _check_1e

CASES = [
    {
        "type": "조작(A)",
        "case_name": "심한 피부 가려움 (강아지) — 조기 종료",
        "tamper_note": "후속 질문 없이 1턴 만에 종료 — 부위·기간·심각도 전부 미확인. completeness 겨냥(명확한 실패, 하한선 테스트)",
        "urgency_level": "YELLOW",
        "chief_complaint": "심한 가려움",
        "conversation": [
            {"role": "user", "content": "강아지가 하루 종일 미친 듯이 긁어요 한 곳을 피가 나도록 긁고 있고 자다가도 일어나서 긁어요 긁는 걸 못 멈추는 것 같아요"},
            {"role": "assistant", "content": "알겠습니다. 피부 문제로 보이니 한 번 진료받아보시는 게 좋겠어요. 예약 도와드릴까요?"},
        ],
    },
    {
        "type": "조작(B)",
        "case_name": "다음다뇨 (고양이) — 중복 질문",
        "tamper_note": "이미 답변받은 발병 시기를 다시 질문, 구토/배변 등 새 정보는 미확인. question_efficiency 겨냥(미묘한 비효율, 정밀 테스트)",
        "urgency_level": "YELLOW",
        "chief_complaint": "다음다뇨",
        "conversation": [
            {"role": "user", "content": "고양이가 요즘 물을 엄청 많이 마셔요 전보다 3배는 더 마시는 것 같고 소변도 엄청 자주 봐요 양도 많아진 것 같고요"},
            {"role": "assistant", "content": "물도 많이 마시고 소변도 자주 많아졌군요. 이런 변화가 언제부터 보이기 시작했는지 알려주실까요?"},
            {"role": "user", "content": "한 2주 정도 된 것 같아요 그리고 요즘 살도 좀 빠진 것 같고 밥은 그대로 먹는데 예전보다 기운이 없어 보여요"},
            {"role": "assistant", "content": "네, 그런데 이런 증상이 정확히 언제부터 시작됐을까요?"},
            {"role": "user", "content": "아까 2주 정도라고 말씀드렸는데... 네 2주요"},
            {"role": "assistant", "content": "알겠습니다. 진료 예약 도와드릴까요?"},
        ],
    },
]

OUT_PATH = Path("/app/ai/agents/eval_cases/triage_judge_adversarial.json")


async def main():
    results = []
    for case in CASES:
        triage_obj = SimpleNamespace(
            urgency_level=case["urgency_level"],
            urgency_level_num=None,
            chief_complaint=case["chief_complaint"],
        )
        chat_history_obj = SimpleNamespace(messages=case["conversation"])

        judge = await _check_1e(triage_obj, chat_history_obj)
        entry = {
            "type": case["type"],
            "case_name": case["case_name"],
            "tamper_note": case["tamper_note"],
            "urgency_level": case["urgency_level"],
            "chief_complaint": case["chief_complaint"],
            "conversation": case["conversation"],
            "judge_status": judge.get("status"),
            "judge_detail": judge.get("detail"),
            "judge_scores": judge.get("scores"),
        }
        results.append(entry)
        print(f"OK: {case['case_name']} -> judge={judge.get('status')} scores={judge.get('scores')}", file=sys.stderr)

    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {OUT_PATH}", file=sys.stderr)


asyncio.run(main())
