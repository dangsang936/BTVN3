# -*- coding: utf-8 -*-
"""Phần dùng chung cho 3 mẫu agent.

Mỗi lượt hội thoại đi qua cùng một khung (giống nhau cho cả 3 mẫu):
  1. _begin_turn : model trích yêu cầu -> BookingRequest (structured output, Pydantic)
                   -> kiểm căn cứ -> ràng buộc dạng dữ liệu cho harness
  2. (mỗi mẫu tự cài) vòng suy luận + gọi tool qua harness
  3. _respond    : model viết câu trả lời -> FinalAnswer (structured output, Pydantic)
  4. _build_result: harness kiểm nội dung câu trả lời (finalize) và đóng gói kết quả + trace
"""
import json
from typing import Any, Callable, Dict, List, Optional

from harness import BudgetLimits, Constraints, Decision, FlightHarnessManager
from harness.harness_manager import Approver
from harness.output_validator import ground_request
from llm_io import StructuredOutputError, structured_call
from prompts import EXTRACT_PROMPT, PROMPT_VERSION, RESPOND_PROMPT
from schemas import BookingRequest, FinalAnswer
from tools import get_flight_tools

PlanApprover = Callable[[Dict[str, Any]], Optional[bool]]


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p["text"] if isinstance(p, dict) and "text" in p else str(p)
                         for p in content if not (isinstance(p, dict) and p.get("type") == "thinking"))
    return str(content)


def tool_results_json(steps_log: List[Dict[str, Any]]) -> str:
    out = []
    for s in steps_log:
        if s.get("type") == "observation":
            try:
                obs = json.loads(s["observation"])
            except Exception:
                obs = s["observation"]
            out.append({"tool": s.get("tool"), "args": s.get("args"), "result": obs})
    return json.dumps(out, ensure_ascii=False) if out else "[]"


class BaseFlightAgent:
    agent_type = "base"

    def __init__(self, user_id: str = "user_customer_1", model=None,
                 approver: Optional[Approver] = None, plan_approver: Optional[PlanApprover] = None,
                 limits: Optional[BudgetLimits] = None, extractor: str = "llm"):
        if model is None:
            from load import get_model
            model = get_model()
        if extractor not in ("llm", "regex"):
            raise ValueError("extractor phải là 'llm' hoặc 'regex'")
        self.user_id, self.model, self.extractor = user_id, model, extractor
        self.tools = get_flight_tools()
        self.tools_map = {t.name: t for t in self.tools}
        self.approver, self.plan_approver, self.limits = approver, plan_approver, limits
        self.harness = FlightHarnessManager(user_id, approver=approver, limits=limits)
        self.turns_history: List[Dict[str, Any]] = []
        self._reset_memory()

    def _reset_memory(self):
        pass

    def set_user(self, user_id: str):
        self.user_id = user_id
        self.harness.set_user(user_id)

    def reset(self):
        self.harness = FlightHarnessManager(self.user_id, approver=self.approver, limits=self.limits)
        self.turns_history = []
        self._reset_memory()

    def run(self, query: str) -> Dict[str, Any]:
        self.reset()
        return self.chat(query)

    def chat(self, user_input: str) -> Dict[str, Any]:
        raise NotImplementedError

    # ------------------------------------------------------------------ 1. trích yêu cầu
    def _begin_turn(self, user_input: str) -> Dict[str, Any]:
        h = self.harness
        h.budget.start_turn()
        trace: Dict[str, Any] = {"type": "extract", "source": "regex"}
        extracted = None
        if self.extractor == "llm":
            msgs = EXTRACT_PROMPT.format_messages(
                previous_request=json.dumps(h.constraints.to_dict(), ensure_ascii=False) or "{}",
                user_message=user_input)
            try:
                res = structured_call(self.model, msgs, BookingRequest, on_llm=h.record_llm)
                req, dropped = ground_request(res.value, user_input, h.constraints.to_dict())
                extracted = Constraints.from_request(req)
                trace.update(source="llm", request=req.model_dump(exclude_none=True),
                             dropped_ungrounded=dropped, attempts=res.attempts)
                if dropped:
                    h.interventions_pending = [{"kind": "UNGROUNDED_FIELD_DROPPED", "reason": ", ".join(dropped)}]
            except StructuredOutputError as e:
                trace.update(source="regex_fallback", attempts=e.attempts)
        h.start_turn(user_input, extracted, reset_budget=False)
        for it in getattr(h, "interventions_pending", []):
            h.interventions.append(it)
        h.interventions_pending = []
        trace["constraints"] = h.constraints.to_dict()
        return trace

    # ------------------------------------------------------------------ 3. trả lời có cấu trúc
    def _respond(self, user_input: str, steps_log: List[Dict[str, Any]], decision: Decision):
        """Trả về (FinalAnswer, attempts). Model lỗi schema quá số lần thử -> harness dựng câu trả lời an toàn."""
        status = {"stop_kind": decision.kind, "reason": decision.reason,
                  "question_for_user": (decision.handoff or {}).get("cau_hoi_cho_nguoi")}
        msgs = RESPOND_PROMPT.format_messages(
            user_request=user_input, constraints_json=self.harness.constraints_json(),
            tool_results=tool_results_json(steps_log), harness_status=json.dumps(status, ensure_ascii=False))
        try:
            res = structured_call(self.model, msgs, FinalAnswer, on_llm=self.harness.record_llm)
            return res.value, res.attempts
        except StructuredOutputError as e:
            return self.harness.fallback_answer(decision), e.attempts

    # ------------------------------------------------------------------ 4. đóng gói
    def _build_result(self, user_input: str, answer: FinalAnswer, decision: Decision,
                      steps_log: List[Dict[str, Any]], extra: Optional[Dict[str, Any]] = None,
                      attempts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        fin = self.harness.finalize(answer, decision, attempts)
        steps_log.append({"type": "final", "answer": fin["answer"],
                          "replaced_by_harness": fin["answer_validation"]["replaced_by_harness"]})
        all_attempts = [a for s in steps_log for a in (s.get("attempts") or [])] + (attempts or [])
        result = {
            "agent_type": self.agent_type,
            "prompt_version": PROMPT_VERSION,
            "query": user_input,
            "user_id": self.user_id,
            **fin,
            "metrics": {
                **fin["budget"],
                "steps": len(steps_log),
                "completed_by_code": fin["completion_report"]["hoan_thanh"],
                "grounding_passed": fin["grounding_report"]["dat"],
                "harness_interventions": len(fin["interventions"]),
                "structured_ok": sum(1 for a in all_attempts if a.get("ok")),
                "schema_failures": sum(1 for a in all_attempts if not a.get("ok")),
                "answer_replaced": fin["answer_validation"]["replaced_by_harness"],
            },
            "steps_log": steps_log,
        }
        if extra:
            result.update(extra)
            result["metrics"].update({k: v for k, v in extra.items() if isinstance(v, (int, float))})
        self.turns_history.append(result)
        return result
