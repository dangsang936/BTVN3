# -*- coding: utf-8 -*-
"""SE373 · Mẫu 1: ReAct (Suy luận -> Hành động -> Quan sát -> Suy luận tiếp).

Model quyết định từng bước lúc chạy; harness bọc quanh MỌI lời gọi tool.
Câu trả lời cuối cũng là một tool call: `final_answer` có args_schema = FinalAnswer (Pydantic),
nên output cuối là dữ liệu có cấu trúc, được validate như mọi tool call khác.
Model trả prose thay vì gọi final_answer -> coi là lỗi định dạng, chuyển sang bước _respond có schema.

Function calling đúng vòng đời của slide:
    model sinh tool_call (id) -> APPLICATION kiểm & thực thi -> ToolMessage(tool_call_id=id) -> model đọc result
Mọi tool_call đều có đúng một ToolMessage cùng id (kể cả khi harness chặn / bỏ qua), trace ghi lại call_id.

Context engineering: system prompt tĩnh (cache được prefix); ràng buộc + yêu cầu nằm trong user message;
lịch sử các lượt cũ được cắt theo ranh giới lượt (giữ `max_history_turns` lượt gần nhất) để tránh context
rot / lost in the middle và không gửi lại token thừa ở mỗi bước.
"""
import json
from typing import List, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import ValidationError

from agents.base import BaseFlightAgent, extract_text
from harness import ANSWERED, Decision
from llm_io import validation_errors
from prompts import REACT_PROMPT, REACT_USER_PROMPT
from schemas import FinalAnswer


@tool("final_answer", args_schema=FinalAnswer)
def final_answer_tool(status: str, message: str, booking_code: Optional[str] = None,
                      flight_id: Optional[str] = None, suggested_flight_ids: Optional[List[str]] = None,
                      question_for_user: Optional[str] = None) -> str:
    """Gửi câu trả lời cuối cho người dùng. Gọi đúng một lần khi đã xong hoặc khi cần hỏi người dùng."""
    return "received"


class ReActFlightAgent(BaseFlightAgent):
    agent_type = "ReAct"
    max_format_retries = 1
    max_history_turns = 3

    def _reset_memory(self):
        self.model_with_tools = self.model.bind_tools(self.tools + [final_answer_tool])
        self.messages = []

    def _trim_history(self):
        """Giữ system + `max_history_turns` lượt gần nhất. Cắt tại HumanMessage (đầu lượt) nên không bao giờ
        tách một AIMessage có tool_calls khỏi các ToolMessage tương ứng."""
        starts = [i for i, m in enumerate(self.messages) if isinstance(m, HumanMessage)]
        if len(starts) > self.max_history_turns:
            cut = starts[-self.max_history_turns]
            self.messages = self.messages[:1] + self.messages[cut:]

    def chat(self, user_input: str):
        h = self.harness
        steps = [self._begin_turn(user_input)]
        # 01 Dựng ngữ cảnh: system = instruction TĨNH; user = ràng buộc (dữ liệu) + yêu cầu, bọc thẻ XML
        system = REACT_PROMPT.format_messages()[0]
        self.messages = [system] + self.messages[1:]
        self.messages += REACT_USER_PROMPT.format_messages(constraints_json=h.constraints_json(),
                                                           user_request=user_input)
        self._trim_history()

        decision, answer, attempts = Decision(), None, []
        format_retries, it = 0, 0
        while not decision.stop:
            it += 1
            ai = self.model_with_tools.invoke(self.messages)              # 02 Model đề xuất
            h.record_llm(ai)
            self.messages.append(ai)
            calls = getattr(ai, "tool_calls", None) or []
            thought = extract_text(ai.content)

            if not calls:                                                  # prose -> sai interface
                attempts.append({"attempt": it, "mode": "react_final_answer_tool", "ok": False,
                                 "error": "Model trả văn bản thay vì gọi final_answer"})
                steps.append({"type": "format_error", "content": thought[:300]})
                decision = Decision(True, ANSWERED, "Model thôi gọi tool (không qua final_answer).")
                break

            for i, tc in enumerate(calls):
                tc_id = tc.get("id") or f"call_{it}_{i}"
                if tc["name"] == "final_answer":
                    try:
                        answer = FinalAnswer.model_validate(tc["args"])
                        attempts.append({"attempt": it, "mode": "react_final_answer_tool", "ok": True})
                        self.messages.append(ToolMessage(content='{"status":"ok"}', tool_call_id=tc_id,
                                                         name="final_answer"))
                        decision = Decision(True, ANSWERED, "Model gửi final_answer.")
                    except ValidationError as e:
                        errs = validation_errors(e)
                        attempts.append({"attempt": it, "mode": "react_final_answer_tool", "ok": False, "error": errs})
                        steps.append({"type": "format_error", "tool": "final_answer", "errors": errs})
                        self.messages.append(ToolMessage(
                            content=json.dumps({"status": "invalid_param", "errors": errs,
                                                "hint": "Gọi lại final_answer với dữ liệu đúng schema."},
                                               ensure_ascii=False), tool_call_id=tc_id, name="final_answer"))
                        format_retries += 1
                        if format_retries > self.max_format_retries:
                            decision = Decision(True, ANSWERED, "final_answer sai schema quá số lần thử.")
                    rest = calls[i + 1:]
                else:
                    steps.append({"type": "tool_call", "call_id": tc_id, "tool": tc["name"], "args": tc["args"],
                                  "thought": thought})
                    obs, d = h.run_tool(tc["name"], tc["args"], self.tools_map)   # 03-05: application thực thi
                    # tool result gắn với đúng tool call qua tool_call_id
                    self.messages.append(ToolMessage(content=obs, tool_call_id=tc_id, name=tc["name"]))
                    steps.append({"type": "observation", "call_id": tc_id, "tool": tc["name"], "args": tc["args"],
                                  "observation": obs})
                    if d.stop:
                        decision = d
                    rest = calls[i + 1:]
                if decision.stop:
                    # Mọi tool_call phải có ToolMessage tương ứng, nếu không lượt sau API báo lỗi
                    for r in rest:
                        self.messages.append(ToolMessage(
                            content='{"status":"error","error":"skipped","hint":"harness đã dừng vòng lặp"}',
                            tool_call_id=r.get("id") or "skipped", name=r.get("name")))
                    break
            if not decision.stop:
                decision = h.check_budget()

        if answer is None:            # harness dừng (GOAL/LOOP/...) hoặc model không gửi final_answer hợp lệ
            answer, extra_attempts = self._respond(user_input, steps, decision)
            attempts += extra_attempts
            self.messages.append(AIMessage(content=answer.message))

        return self._build_result(user_input, answer, decision, steps, {"iterations": it}, attempts)
