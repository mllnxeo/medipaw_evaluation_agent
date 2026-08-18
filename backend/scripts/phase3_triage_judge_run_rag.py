"""Phase 3 Triage RAG 재생성 — RAG 시드 적재 후 재생성한 대화에 _check_1e 판정."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "/app")

from ai.agents.evaluation.case_eval import _check_1e

STATE_FILES = {
    "심한 피부 가려움 (강아지)": "/tmp/phase3/case1_skin_rag2.json",
    "다음다뇨 (고양이)": "/tmp/phase3/case2_pud_rag.json",
}

OUT_PATH = Path("/app/ai/agents/eval_cases/triage_judge_calibration_rag.json")


async def main():
    results = []
    for name, path in STATE_FILES.items():
        with open(path, encoding="utf-8") as f:
            state = json.load(f)

        data = state["triage_state"]["last_complete"]["data"]
        triage_obj = SimpleNamespace(
            urgency_level=data["urgency"],
            urgency_level_num=None,
            chief_complaint=", ".join(data.get("chief_complaints") or []),
        )
        chat_history_obj = SimpleNamespace(messages=state["history"])

        judge = await _check_1e(triage_obj, chat_history_obj)
        entry = {
            "case_name": name,
            "urgency": data["urgency"],
            "chief_complaint": triage_obj.chief_complaint,
            "suspected_conditions": data.get("suspected_conditions"),
            "turn_count": state["turn_count"],
            "conversation": state["history"],
            "judge_status": judge.get("status"),
            "judge_detail": judge.get("detail"),
            "judge_scores": judge.get("scores"),
        }
        results.append(entry)
        print(f"OK: {name} -> judge={judge.get('status')} scores={judge.get('scores')}", file=sys.stderr)

    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {OUT_PATH}", file=sys.stderr)


asyncio.run(main())
