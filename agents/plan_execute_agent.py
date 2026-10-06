# -*- coding: utf-8 -*-
"""SE373 · Mẫu 2: Plan-then-Execute.

    Goal -> Model sinh kế hoạch (Plan, Pydantic) -> NGƯỜI DUYỆT -> Bước 1 -> Bước 2 -> ... -> Kết quả
                                                       | từ chối -> dừng, bàn giao

Gọi model MỘT lần để sinh trọn kế hoạch, duyệt kế hoạch (code + người nếu có), rồi thực thi
tuần tự bằng code. Kế hoạch không được sửa giữa chừng: bước nào thất bại thì dừng và bàn giao
("kế hoạch lỗi thời" là rủi ro chính của mẫu này theo slide).
"""
from typing import Any, Dict, List

from agents.base import BaseFlightAgent
from agents.planner import make_plan, obs_status, resolve_placeholders
from harness import ANSWERED, HUMAN, Decision
from harness.output_validator import validate_plan

PLAN_FAILED = "PLAN_FAILED"
OK_STATUSES = {"ok", "not_found"}   # not_found là dữ liệu hợp lệ (ví dụ mã vé không tồn tại)


class PlanThenExecuteFlightAgent(BaseFlightAgent):
    agent_type = "Plan-then-Execute"

    def _reset_memory(self):
        self.history: List[Dict[str, str]] = []

    def _approve_plan(self, plan) -> Decision:
        issues = validate_plan(plan, self.harness.constraints)
        if issues:
            return self.harness._stop(PLAN_FAILED, "Kế hoạch bị người duyệt (code) từ chối: " + "; ".join(issues),
                                      "Kế hoạch không hợp lệ. Bạn mô tả lại yêu cầu được không?")
        if self.plan_approver and plan.steps:
            ans = self.plan_approver({"plan": [s.model_dump(exclude_none=True) for s in plan.steps],
                                      "rang_buoc": self.harness.constraints.to_dict()})
            if ans is None:
                return self.harness._stop(HUMAN, "Kế hoạch đang chờ duyệt.", "Bạn có duyệt kế hoạch này không?")
            if ans is False:
                return self.harness._stop(HUMAN, "Người dùng từ chối kế hoạch.", "Bạn muốn điều chỉnh gì?")
        return Decision()

    def chat(self, user_input: str):
        h = self.harness
        steps: List[Dict[str, Any]] = [self._begin_turn(user_input)]
        self.history.append({"role": "user", "content": user_input})

        # PHA 1: lập kế hoạch (1 lần gọi model, output là Plan đã validate)
        plan, plan_attempts = make_plan(self.model, h, self.history, user_input)
        steps.append({"type": "plan", "plan": plan.model_dump(exclude_none=True), "attempts": plan_attempts})

        # Duyệt trước khi chạy
        decision = self._approve_plan(plan)
        if not decision.stop and plan.status != "ready":
            q = plan.question_for_user or "Bạn bổ sung thông tin giúp tôi?"
            decision = Decision(True, HUMAN, f"Planner: {plan.status}",
                                h.handoff(HUMAN, f"Planner trả {plan.status}", q))

        # PHA 2: thực thi tuần tự bằng code, không hỏi lại model
        if not decision.stop:
            for s in plan.steps:
                args, err = resolve_placeholders(s, h)
                if err:
                    decision = h._stop(PLAN_FAILED, f"Bước {s.step_id}: {err}",
                                       "Kế hoạch không còn đúng với dữ liệu thực tế. Bạn muốn xử lý thế nào?")
                    break
                call_id = f"plan_step_{s.step_id}"     # gắn tool result với đúng tool call trong trace
                steps.append({"type": "tool_call", "call_id": call_id, "step_id": s.step_id, "tool": s.tool,
                              "args": args, "objective": s.objective})
                obs, d = h.run_tool(s.tool, args, self.tools_map)   # application kiểm & thực thi
                steps.append({"type": "observation", "call_id": call_id, "step_id": s.step_id, "tool": s.tool,
                              "args": args, "observation": obs})
                if d.stop:
                    decision = d
                    break
                if obs_status(obs) not in OK_STATUSES:
                    decision = h._stop(PLAN_FAILED,
                                       f"Bước {s.step_id} ({s.tool}) trả về {obs_status(obs)}; kế hoạch tĩnh không tự điều chỉnh.",
                                       "Bước trong kế hoạch thất bại. Bạn muốn đổi yêu cầu không?")
                    break
            if not decision.stop:
                decision = Decision(True, ANSWERED, "Đã chạy hết kế hoạch.")

        # PHA 3: câu trả lời có cấu trúc (FinalAnswer)
        answer, attempts = self._respond(user_input, steps, decision)
        self.history.append({"role": "assistant", "content": answer.message})
        return self._build_result(user_input, answer, decision, steps,
                                  {"plan": plan.model_dump(exclude_none=True), "plan_steps": len(plan.steps),
                                   "replans": 0}, attempts)
