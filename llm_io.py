# -*- coding: utf-8 -*-
"""Gọi model và nhận về dữ liệu ĐÃ VALIDATE theo schema Pydantic.

Hai cách lấy structured output:
  1. Constrained output: `model.with_structured_output(Schema)`: API ép output theo schema.
     Mạnh hơn "chỉ trả JSON" trong prompt, nhưng mỗi nhà cung cấp hỗ trợ một tập JSON Schema khác nhau.
  2. Prompt-only (dự phòng): gửi JSON Schema trong prompt, tự bóc JSON và validate.
     Model vẫn có thể thêm prose, bọc code fence, thiếu field, sai enum, sai kiểu.

Dù dùng cách nào, ứng dụng LUÔN validate lại bằng Pydantic (`Schema.model_validate`).
Sai schema -> gửi lại lỗi validation cho model sửa (tối đa `max_retries` lần) -> vẫn sai thì
ném StructuredOutputError để caller dùng phương án an toàn. Mỗi lần thử được ghi vào trace.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    def __init__(self, schema: str, attempts: List[Dict[str, Any]]):
        self.schema, self.attempts = schema, attempts
        super().__init__(f"Không nhận được {schema} hợp lệ sau {len(attempts)} lần: "
                         f"{attempts[-1].get('error') if attempts else ''}")


@dataclass
class StructuredResult:
    value: BaseModel
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    raw_messages: List[Any] = field(default_factory=list)


def extract_json_text(text: str) -> str:
    """Bóc JSON ra khỏi prose / code fence (``` json ... ```). Không đoán nội dung."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


def validation_errors(e: ValidationError) -> List[str]:
    return [f"{'.'.join(str(x) for x in err['loc']) or '(root)'}: {err['msg']}" for err in e.errors()]


def validate_json(schema: Type[T], text: str) -> T:
    """Validate chuỗi output của model theo schema (ném ValidationError / ValueError)."""
    return schema.model_validate_json(extract_json_text(text))


def _content_text(msg: Any) -> str:
    c = getattr(msg, "content", msg)
    if isinstance(c, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return str(c)


def structured_call(model, messages: List[BaseMessage], schema: Type[T], *, max_retries: int = 1,
                    on_llm: Optional[Any] = None, prefer_constrained: bool = True) -> StructuredResult:
    """Gọi model, trả về instance `schema` đã validate. `on_llm(ai_msg)` để harness đếm token."""
    attempts: List[Dict[str, Any]] = []
    raws: List[Any] = []
    convo = list(messages)
    use_constrained = prefer_constrained and hasattr(model, "with_structured_output")

    for attempt in range(max_retries + 1):
        mode = "constrained" if use_constrained else "prompt_only"
        raw_msg, text = None, ""

        def _count(msg):
            if msg is not None:
                raws.append(msg)
                if on_llm:
                    on_llm(msg)

        try:
            if use_constrained:
                out = model.with_structured_output(schema, include_raw=True).invoke(convo)
                raw_msg = out.get("raw")
                _count(raw_msg)
                parsed = out.get("parsed")
                if parsed is not None:
                    data = parsed.model_dump() if isinstance(parsed, BaseModel) else parsed
                    text = json.dumps(data, ensure_ascii=False, default=str)
                    value = schema.model_validate(data)          # validate lại phía ứng dụng
                    attempts.append({"attempt": attempt + 1, "mode": mode, "ok": True})
                    return StructuredResult(value, attempts, raws)
                text = _content_text(raw_msg) if raw_msg is not None else ""
                if not text and raw_msg is not None and getattr(raw_msg, "tool_calls", None):
                    text = json.dumps(raw_msg.tool_calls[0].get("args", {}), ensure_ascii=False)
                if not text:
                    raise ValueError(f"parsing_error: {out.get('parsing_error')}")
            else:
                schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
                prompt_only = convo + [HumanMessage(content=(
                    "<output_format>\nChỉ trả về MỘT object JSON hợp lệ theo JSON Schema dưới đây, "
                    "không prose, không code fence.\n" + schema_json + "\n</output_format>"))]
                raw_msg = model.invoke(prompt_only)
                _count(raw_msg)
                text = _content_text(raw_msg)

            value = validate_json(schema, text)
            attempts.append({"attempt": attempt + 1, "mode": mode, "ok": True, "parsed_from_text": True})
            return StructuredResult(value, attempts, raws)

        except ValidationError as e:
            errs = validation_errors(e)
            attempts.append({"attempt": attempt + 1, "mode": mode, "ok": False, "error": errs})
            # Gửi lỗi validation lại cho model để tự sửa
            convo = list(messages) + [
                AIMessage(content=text or "(output rỗng)"),
                HumanMessage(content="<validation_error>\nOutput không đúng schema "
                                     f"{schema.__name__}:\n" + "\n".join(errs)
                                     + "\nHãy trả lại output đã sửa, đúng schema.\n</validation_error>"),
            ]
        except Exception as e:  # API không hỗ trợ schema / JSON hỏng
            if "RateLimit" in type(e).__name__ or "429" in str(e):
                raise                                     # lỗi hạ tầng: để caller xử lý
            attempts.append({"attempt": attempt + 1, "mode": mode, "ok": False,
                             "error": f"{type(e).__name__}: {str(e)[:200]}"})
            if use_constrained:                           # constrained không dùng được -> prompt-only
                use_constrained = False
    raise StructuredOutputError(schema.__name__, attempts)
