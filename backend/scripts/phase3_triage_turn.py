"""Phase 3 Triage 2차 시도 — 실제 TriageAgent를 턴 단위로 구동하는 드라이버.

한 번 실행 = 한 턴. 대화 상태(history, triage_state 등)는 JSON 파일에
저장해 다음 턴에 이어받는다. 사람이 매 턴 봇의 실제 질문을 보고 다음
보호자 발화를 직접 정해서 넘기는 구조 — 대사를 미리 다 써놓지 않는다.

사용법:
  python phase3_triage_turn.py <state_file> <pet_json> "<user_message>"

최초 턴은 state_file이 없으면 빈 상태로 시작한다.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from ai.agents.triage.agent import TriageAgent
from ai.orchestrator.contracts import Flow, Phase, SessionContext


async def main():
    state_path = Path(sys.argv[1])
    pet_info = json.loads(sys.argv[2])
    user_message = sys.argv[3]

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {"history": [], "triage_state": {}, "turn_count": 0}

    ctx = SessionContext(
        session_id=0, userid=0, petid=0,
        pet_info=pet_info,
        hospitalid=None, emrid=None, scheduleid=None,
        user_message=user_message,
        history=state["history"],
        phase=Phase.PRE_BOOKING,
        active_flow=Flow.TRIAGING if state["turn_count"] > 0 else Flow.IDLE,
        triage_state=state["triage_state"],
        db=None,
    )

    agent = TriageAgent()
    result = await agent.run(ctx, {})

    # 대화 기록 갱신
    state["history"].append({"role": "user", "content": user_message})
    state["history"].append({"role": "assistant", "content": result.reply})
    patch = result.state_patch or {}
    if "triage_state" in patch:
        state["triage_state"] = patch["triage_state"]
    state["turn_count"] += 1
    state["last_active_flow"] = patch.get("active_flow", "triaging")

    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== 봇 응답 ===")
    print(result.reply)
    if result.quick_replies:
        print("--- quick_replies ---")
        for q in result.quick_replies:
            print(" -", q)
    print(f"--- active_flow(다음 턴): {state['last_active_flow']} | turn_count={state['turn_count']} ---")


asyncio.run(main())
