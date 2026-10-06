# -*- coding: utf-8 -*-
"""Kiểm Ý NGHĨA tham số tool trước khi thực thi.

    {"name": "get_component_owner", "arguments": {"component": "payment-api-v2"}}
    -> component đúng kiểu string, nhưng hệ thống KHÔNG có component đó.
    "Đúng kiểu không đồng nghĩa đúng ý nghĩa."

Thứ tự kiểm một tool call trong harness (application quyết định có thực thi hay không):
  1. Tên tool có trong danh sách tool đã khai báo không                   -> invalid_param
  2. Quyền của tài khoản đăng nhập                                         -> denied / cần người duyệt
  3. Đúng schema  : args_schema Pydantic (kiểu, pattern, field thừa)       -> invalid_param
  4. Đúng ý nghĩa : đối chiếu với dữ liệu thật của hệ thống (file này)     -> invalid_param + hint
  5. Ràng buộc người dùng (trước book_flight), người duyệt, rồi mới thực thi  (harness_manager.run_tool)
Chỉ khi qua hết, application mới gọi hàm. Model chỉ đề xuất hành động; nó không có thêm quyền
hay thêm dữ liệu chỉ vì đã sinh ra tool call.
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional

from tools.mock_database import AIRPORTS, db


@dataclass
class ArgIssue:
    param: str
    message: str
    hint: str


def check_tool_semantics(tool_name: str, args: Dict[str, Any]) -> Optional[ArgIssue]:
    """None nếu tham số có ý nghĩa hợp lệ; ngược lại trả lỗi đầu tiên (param, message, hint)."""
    if tool_name == "search_flights":
        orig = db.find_airport_code(str(args.get("origin", "")))
        dest = db.find_airport_code(str(args.get("destination", "")))
        supported = ", ".join(f"{c}={i['city']}" for c, i in AIRPORTS.items())
        if not orig:
            return ArgIssue("origin", f"Không có sân bay '{args.get('origin')}' trong hệ thống.",
                            f"Dùng một trong các mã: {supported}.")
        if not dest:
            return ArgIssue("destination", f"Không có sân bay '{args.get('destination')}' trong hệ thống.",
                            f"Dùng một trong các mã: {supported}.")
        if orig == dest:
            return ArgIssue("destination", f"Điểm đi và điểm đến trùng nhau ({orig}).",
                            "Hỏi lại người dùng chặng bay, không tự đoán.")

    if tool_name in ("get_flight_details", "book_flight"):
        fid = str(args.get("flight_id", ""))
        if not db.get_flight_by_id(fid):
            return ArgIssue("flight_id", f"Mã chuyến {fid} đúng định dạng nhưng không tồn tại trong hệ thống.",
                            "Gọi search_flights để lấy mã chuyến có thật; không tự đặt mã chuyến.")
    return None
