# -*- coding: utf-8 -*-
"""Bộ lập kế hoạch dùng chung cho Plan-then-Execute và mẫu Lai.

Planner trả về `Plan` (Pydantic) qua structured output -> kế hoạch là DỮ LIỆU đã validate,
nên duyệt được trước khi chạy (validate_plan) và ước lượng được chi phí (số bước).
Bước sau tham chiếu kết quả bước trước qua placeholder (code điền khi chạy):
  $BEST_FLIGHT   -> chuyến tốt nhất thỏa mọi ràng buộc trong các kết quả đã tìm
  $LAST_BOOKING  -> mã vé vừa tạo trong phiên
"""
import json
from typing import Any, Dict, List, Optional, Tuple

from llm_io import StructuredOutputError, structured_call
from prompts import PLANNER_PROMPT
from schemas import Plan, PlanStep


def make_plan(model, harness, history: List[Dict[str, str]], user_input: str,
              feedback: Optional[List[Dict[str, Any]]] = None) -> Tuple[Plan, List[Dict[str, Any]]]:
    """Trả về (Plan đã validate, các lần thử). Planner lỗi schema -> Plan needs_user_input an toàn."""
    hist = "\n".join(f"{t['role']}: {t['content']}" for t in history[-6:-1]) or "(trống)"
    msgs = PLANNER_PROMPT.format_messages(
        constraints_json=harness.constraints_json(),
        history=hist,
        user_request=user_input,
        observations=json.dumps(feedback, ensure_ascii=False) if feedback else "(chưa chạy bước nào)",
    )
    try:
        res = structured_call(model, msgs, Plan, on_llm=harness.record_llm)
        return res.value, res.attempts
    except StructuredOutputError as e:
        return Plan(status="needs_user_input", steps=[],
                    question_for_user="Tôi chưa lập được kế hoạch hợp lệ. Bạn mô tả lại yêu cầu giúp tôi?"), e.attempts


def resolve_placeholders(step: PlanStep, harness) -> Tuple[Dict[str, Any], Optional[str]]:
    args = step.tool_args()
    if args.get("flight_id") == "$BEST_FLIGHT":
        best = harness.best_candidate()
        if not best:
            return args, "Không có chuyến nào thỏa mọi ràng buộc để điền $BEST_FLIGHT."
        args["flight_id"] = best["flight_id"]
    if args.get("booking_code") == "$LAST_BOOKING":
        if not harness.session_bookings:
            return args, "Chưa có vé nào để điền $LAST_BOOKING."
        args["booking_code"] = harness.session_bookings[-1]
    return args, None


def obs_status(obs: str) -> str:
    try:
        return json.loads(obs).get("status", "?")
    except Exception:
        return "?"
