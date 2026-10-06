# -*- coding: utf-8 -*-
"""SE373 · Mẫu 3: Lai "ReAct + Plan" (slide "Mẫu lai").

    Lập kế hoạch -> Thực thi k bước -> Observation đổi đáng kể? --có--> LẬP LẠI KẾ HOẠCH
                                                |
                                              không -> chạy tiếp phần còn lại / xong

Khác Plan-then-Execute: khi thực tế lệch kế hoạch (hết chỗ, bị chặn vì vi phạm ràng buộc,
không tìm thấy, tool lỗi), planner được gọi lại với các observation vừa có để sinh Plan mới.
Khác ReAct: model không quyết định từng bước mà theo cụm k bước, nên ít lời gọi model hơn và
kế hoạch (Plan, Pydantic) vẫn duyệt được trước khi chạy. Giới hạn max_replans để không lặp vô hạn.
"""
import json
from typing import Any, Dict, List

from agents.base import BaseFlightAgent
from agents.planner import make_plan, obs_status, resolve_placeholders
from harness import ANSWERED, HUMAN, STALL, Decision
from harness.output_validator import validate_plan

SIGNIFICANT = {"error", "denied", "invalid_param", "not_found", "rejected_by_human"}


class HybridFlightAgent(BaseFlightAgent):
    agent_type = "Lai (Plan + ReAct)"

    def __init__(self, *args, k: int = 2, max_replans: int = 2, **kwargs):
        self.k, self.max_replans = k, max_replans
        super().__init__(*args, **kwargs)

    def _reset_memory(self):
        self.history: List[Dict[str, str]] = []

    def _significant(self, tool: str, obs: str, args: Dict[str, Any]) -> str:
        """Mô tả thay đổi đáng kể so với kỳ vọng của kế hoạch, hoặc '' nếu không có."""
        st = obs_status(obs)
        if st in SIGNIFICANT and not (tool == "check_booking_status" and st == "not_found"):
            return f"{tool} trả về {st}"
        c = self.harness.constraints
        if tool == "search_flights" and st == "ok":
            flights = json.loads(obs).get("flights") or []
            if c.flight_id:
                f = next((x for x in flights if x["flight_id"] == c.flight_id), None)
                if f and f["seats_available"] == 0:
                    return f"Chuyến yêu cầu {c.flight_id} đã hết chỗ"
                if f is None:
                    return f"Không thấy chuyến yêu cầu {c.flight_id} trong kết quả"
            if c.intent == "book" and self.harness.best_candidate() is None:
                return "Không có chuyến nào thỏa mọi ràng buộc"
        if tool == "get_flight_details" and st == "ok" and json.loads(obs)["flight"]["seats_available"] == 0:
            return f"Chuyến {args.get('flight_id')} đã hết chỗ"
        return ""

    def chat(self, user_input: str):
        h = self.harness
        steps: List[Dict[str, Any]] = [self._begin_turn(user_input)]
        self.history.append({"role": "user", "content": user_input})
        feedback: List[Dict[str, Any]] = []
        replans = 0
        decision = Decision()

        plan, attempts = make_plan(self.model, h, self.history, user_input)
        steps.append({"type": "plan", "version": 0, "plan": plan.model_dump(exclude_none=True), "attempts": attempts})
        queue = list(plan.steps)

        while not decision.stop:
            issues = validate_plan(plan, h.constraints)
            if issues:
                decision = h._stop(HUMAN, "Kế hoạch bị người duyệt (code) từ chối: " + "; ".join(issues),
                                   "Bạn mô tả lại yêu cầu được không?")
                break
            if not queue:
                if plan.status != "ready" and plan.question_for_user:
                    decision = Decision(True, HUMAN, f"Planner: {plan.status}",
                                        h.handoff(HUMAN, f"Planner trả {plan.status}", plan.question_for_user))
                else:
                    decision = Decision(True, ANSWERED, "Kế hoạch đã chạy xong.")
                break

            chunk, queue = queue[:self.k], queue[self.k:]
            change = ""
            for s in chunk:                                   # Thực thi k bước
                args, err = resolve_placeholders(s, h)
                if err:
                    change = err
                    feedback.append({"tool": s.tool, "error": err})
                    break
                call_id = f"plan{replans}_step_{s.step_id}"   # gắn tool result với đúng tool call
                steps.append({"type": "tool_call", "call_id": call_id, "tool": s.tool, "args": args,
                              "objective": s.objective})
                obs, d = h.run_tool(s.tool, args, self.tools_map)   # application kiểm & thực thi
                steps.append({"type": "observation", "call_id": call_id, "tool": s.tool, "args": args,
                              "observation": obs})
                feedback.append({"tool": s.tool, "args": args, "result": json.loads(obs)})
                if d.stop:
                    decision = d
                    break
                change = self._significant(s.tool, obs, args)
                if change:
                    break
            if decision.stop:
                break
            if change:                                         # Observation đổi đáng kể -> lập lại
                if replans >= self.max_replans:
                    decision = h._stop(STALL, f"Đã lập lại kế hoạch {replans} lần mà vẫn lệch: {change}",
                                       h._stall_question())
                    break
                replans += 1
                plan, attempts = make_plan(self.model, h, self.history, user_input, feedback=feedback)
                steps.append({"type": "replan", "version": replans, "trigger": change,
                              "plan": plan.model_dump(exclude_none=True), "attempts": attempts})
                queue = list(plan.steps)
            decision = decision if decision.stop else h.check_budget()

        answer, attempts = self._respond(user_input, steps, decision)
        self.history.append({"role": "assistant", "content": answer.message})
        return self._build_result(user_input, answer, decision, steps, {"replans": replans}, attempts)
