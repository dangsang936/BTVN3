# -*- coding: utf-8 -*-
"""Kiểm NỘI DUNG của output đã đúng schema ("Đúng schema": schema kiểm cấu trúc,
không kiểm tính đúng đắn của nội dung; slide "Tool validation": đúng kiểu không đồng nghĩa đúng ý nghĩa).

Ba lớp kiểm cho mỗi output của model:
  1. Parse JSON           (llm_io.extract_json_text)
  2. Đúng schema Pydantic (llm_io.structured_call -> Schema.model_validate)
  3. Đúng ý nghĩa         (file này): đối chiếu với lời người dùng, kết quả tool và CSDL
"""
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from schemas import BookingRequest, FinalAnswer, Plan
from tools.mock_database import AIRPORTS, db

_ALIASES = {
    "HAN": ["ha noi", "hanoi", "noi bai"], "SGN": ["ho chi minh", "hcm", "sai gon", "saigon", "tan son nhat"],
    "DAD": ["da nang", "danang"], "CXR": ["nha trang", "cam ranh"], "PQC": ["phu quoc"], "HPH": ["hai phong"],
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


# ------------------------------------------------------------------ 1. yêu cầu trích bởi model
def ground_request(req: BookingRequest, user_text: str, previous: Dict[str, Any]) -> Tuple[BookingRequest, List[str]]:
    """Bỏ các field model điền mà KHÔNG có căn cứ trong lời người dùng / yêu cầu trước đó.
    Trả về (yêu cầu đã làm sạch, danh sách field bị bỏ)."""
    t, raw = norm(user_text), user_text.upper()
    data = req.model_dump()
    dropped = []

    def keep_if(field: str, ok: bool):
        if data.get(field) not in (None, False, "") and not ok and data[field] != previous.get(field):
            dropped.append(f"{field}={data[field]}")
            data[field] = None if field != "prefer_cheapest" else False

    for f in ("origin", "destination"):
        code = data.get(f)
        if code:
            keep_if(f, code in raw or any(a in t for a in _ALIASES.get(code, [])))
    if data.get("flight_id"):
        keep_if("flight_id", data["flight_id"].replace(" ", "") in raw.replace(" ", ""))
    if data.get("booking_code"):
        keep_if("booking_code", data["booking_code"] in raw)
    if data.get("passenger_id"):
        keep_if("passenger_id", data["passenger_id"] in raw)
    if data.get("passenger_name"):
        keep_if("passenger_name", norm(data["passenger_name"]) in t)
    if data.get("date"):
        y, m, d = data["date"].split("-")
        keep_if("date", data["date"] in user_text
                or re.search(rf"\b0?{int(d)}\s*[/\-.]\s*0?{int(m)}\b", user_text) is not None
                or re.search(rf"ngay\s+0?{int(d)}\s+thang\s+0?{int(m)}\b", t) is not None)
    if data.get("max_price") is not None:
        keep_if("max_price", re.search(r"duoi|toi da|khong qua|<", t) is not None)
    keep_if("prefer_cheapest", re.search(r"re nhat|gia thap nhat|cheapest", t) is not None)
    try:
        return BookingRequest.model_validate(data), dropped
    except Exception:
        return req, dropped


# ------------------------------------------------------------------ 2. kế hoạch
def validate_plan(plan: Plan, constraints) -> List[str]:
    """Người duyệt bằng code: kế hoạch có hợp lý với yêu cầu không (trước khi chạy bước nào)."""
    issues = []
    for s in plan.steps:
        if s.tool == "book_flight" and constraints.intent != "book":
            issues.append(f"Bước {s.step_id}: người dùng không yêu cầu đặt vé")
        if s.tool == "cancel_flight_booking" and constraints.intent != "cancel":
            issues.append(f"Bước {s.step_id}: người dùng không yêu cầu hủy vé")
        if s.tool == "book_flight" and s.flight_id not in (None, "$BEST_FLIGHT") and \
                not re.match(r"^(VN|VJ|QH)\d{3,4}$", s.flight_id or ""):
            issues.append(f"Bước {s.step_id}: flight_id '{s.flight_id}' không hợp lệ")
        if s.tool == "book_flight" and constraints.flight_id and s.flight_id not in (constraints.flight_id, "$BEST_FLIGHT"):
            issues.append(f"Bước {s.step_id}: tự đổi sang chuyến {s.flight_id}, người dùng yêu cầu {constraints.flight_id}")
    return issues


# ------------------------------------------------------------------ 3. câu trả lời cuối
def validate_answer(ans: FinalAnswer, harness) -> List[str]:
    """Đối chiếu FinalAnswer với kết quả tool đã nhận và với CSDL."""
    errs = []
    seen = set(harness.seen_flights)
    if ans.status == "booked":
        rep = harness.completion_report()
        if not rep["hoan_thanh"]:
            errs.append("status=booked nhưng tiêu chí hoàn thành (code) không đạt: " + rep["ly_do"])
        if ans.booking_code not in harness.session_bookings:
            errs.append(f"booking_code {ans.booking_code} không do phiên này tạo")
    if ans.booking_code and ans.status != "booked":
        known = ans.booking_code in harness.session_bookings or ans.booking_code in " ".join(harness.observations)
        if not known:
            errs.append(f"booking_code {ans.booking_code} không có trong kết quả tool")
    for fid in [ans.flight_id, *ans.suggested_flight_ids]:
        if fid and fid not in seen and fid not in " ".join(harness.observations):
            errs.append(f"flight_id {fid} không có trong kết quả tool")
    for fid in ans.suggested_flight_ids:
        f = harness.seen_flights.get(fid)
        if f and f.get("seats_available", 1) == 0:
            errs.append(f"đề xuất chuyến {fid} đã hết chỗ")
    return errs
