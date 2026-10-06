# -*- coding: utf-8 -*-
"""SE373 · Ngân sách vòng lặp: bước · token · thời gian · chi phí.

ngân sách được kiểm CUỐI CÙNG sau mỗi observation; nếu đặt lên đầu
thì mọi lỗi đều báo về là "hết ngân sách" và ta mất chẩn đoán.
"""
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# Đơn giá tham khảo (USD / 1 triệu token). Chỉnh qua biến môi trường cho đúng model đang dùng.
PRICE_IN = float(os.getenv("PRICE_INPUT_PER_M", "0.10"))
PRICE_OUT = float(os.getenv("PRICE_OUTPUT_PER_M", "0.40"))


@dataclass
class BudgetLimits:
    max_llm_calls: int = 10
    max_tool_calls: int = 12
    max_tokens: int = 40_000
    max_seconds: float = 120.0
    max_cost_usd: float = 0.05


@dataclass
class BudgetTracker:
    limits: BudgetLimits = field(default_factory=BudgetLimits)
    llm_calls: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    started_at: float = field(default_factory=time.time)

    def start_turn(self):
        self.llm_calls = self.tool_calls = self.tokens_in = self.tokens_out = 0
        self.started_at = time.time()

    def record_llm(self, ai_msg: Any):
        self.llm_calls += 1
        usage = getattr(ai_msg, "usage_metadata", None) or {}
        self.tokens_in += int(usage.get("input_tokens", 0) or 0)
        self.tokens_out += int(usage.get("output_tokens", 0) or 0)

    def record_tool(self):
        self.tool_calls += 1

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def cost_usd(self) -> float:
        return self.tokens_in / 1e6 * PRICE_IN + self.tokens_out / 1e6 * PRICE_OUT

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at

    def exceeded(self) -> Optional[str]:
        L = self.limits
        if self.llm_calls >= L.max_llm_calls:
            return f"BUDGET_STEPS · Đã gọi LLM {self.llm_calls}/{L.max_llm_calls} lần."
        if self.tool_calls >= L.max_tool_calls:
            return f"BUDGET_TOOLS · Đã gọi tool {self.tool_calls}/{L.max_tool_calls} lần."
        if self.tokens >= L.max_tokens:
            return f"BUDGET_TOKENS · Đã dùng {self.tokens:,}/{L.max_tokens:,} token."
        if self.elapsed >= L.max_seconds:
            return f"BUDGET_TIME · Đã chạy {self.elapsed:.1f}/{L.max_seconds}s."
        if self.cost_usd >= L.max_cost_usd:
            return f"BUDGET_COST · Chi phí {self.cost_usd:.4f}/{L.max_cost_usd} USD."
        return None

    def snapshot(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            "elapsed_sec": round(self.elapsed, 2),
        }
