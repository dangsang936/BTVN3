# -*- coding: utf-8 -*-
"""SE373 · Lớp harness 3: KIỂM QUYỀN (chạy TRƯỚC khi thực thi tool).

Ba kết luận có thể có:
  allow    · chạy tiếp
  deny     · cấm hẳn (guest đặt vé, hủy vé người khác, vượt trần cứng, tool lạ)
  approve  · được phép nhưng PHẢI CHỜ NGƯỜI DUYỆT (vượt ngưỡng chi tiêu, hủy vé = tác dụng phụ)

Danh tính người dùng KHÔNG lấy từ tham số do model sinh ra: harness luôn ghi đè user_id
bằng tài khoản đăng nhập (xem FlightHarnessManager._normalize_args).
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from tools.mock_database import USERS, db

ALLOW, DENY, APPROVE = "allow", "deny", "approve"


@dataclass
class PermissionDecision:
    verdict: str
    reason: Optional[str] = None
    # Gói thông tin cho người duyệt (slide: Đang ở đâu / Định làm gì / Vì sao hỏi)
    approval_request: Dict[str, Any] = field(default_factory=dict)


class FlightPermissionChecker:
    READ_ACTIONS = {"search_flights", "get_flight_details", "check_booking_status"}
    WRITE_ACTIONS = {"book_flight"}
    DESTRUCTIVE_ACTIONS = {"cancel_flight_booking"}

    def __init__(self, current_user_id: str = "user_customer_1"):
        self.current_user_id = current_user_id

    def set_user(self, user_id: str):
        self.current_user_id = user_id

    def get_user_info(self) -> Dict[str, Any]:
        return USERS.get(self.current_user_id,
                         {"role": "guest", "name": "Vãng lai", "budget_limit": 0, "approval_threshold": 0})

    def check(self, tool_name: str, args: Dict[str, Any]) -> PermissionDecision:
        user = self.get_user_info()
        role = user["role"]

        if tool_name in self.READ_ACTIONS:
            return PermissionDecision(ALLOW)

        if tool_name in self.WRITE_ACTIONS:
            if role == "guest":
                return PermissionDecision(DENY, f"PERMISSION_DENIED · Tài khoản '{self.current_user_id}' "
                                                f"(guest) không có quyền đặt vé. Cần đăng nhập tài khoản thành viên.")
            flight = db.get_flight_by_id(str(args.get("flight_id", "")))
            if flight:
                price = flight["price"]
                if price > user["budget_limit"]:
                    return PermissionDecision(DENY, f"BUDGET_EXCEEDED · Giá {price:,} vượt trần cứng "
                                                    f"{user['budget_limit']:,} của tài khoản.")
                if price > user["approval_threshold"]:
                    return PermissionDecision(
                        APPROVE,
                        f"NEEDS_APPROVAL · Giá {price:,} vượt ngưỡng tự duyệt {user['approval_threshold']:,}.",
                        {
                            "dinh_lam_gi": f"book_flight {flight['flight_id']} {flight['date']} "
                                           f"{flight['departure_time']} · {price:,} VNĐ · hành khách "
                                           f"{args.get('passenger_name')}",
                            "vi_sao_hoi": f"Vượt ngưỡng tự duyệt {user['approval_threshold']:,} VNĐ",
                        },
                    )
            return PermissionDecision(ALLOW)

        if tool_name in self.DESTRUCTIVE_ACTIONS:
            if role == "guest":
                return PermissionDecision(DENY, "PERMISSION_DENIED · Khách vãng lai không có quyền hủy vé.")
            code = str(args.get("booking_code", ""))
            booking = db.get_booking(code)
            if booking and role != "admin" and booking.get("user_id") != self.current_user_id:
                return PermissionDecision(DENY, f"PERMISSION_DENIED · Vé '{code}' thuộc tài khoản khác.")
            return PermissionDecision(
                APPROVE,
                f"NEEDS_APPROVAL · Hủy vé {code} là hành động có tác dụng phụ, không hoàn tác được.",
                {"dinh_lam_gi": f"cancel_flight_booking {code}", "vi_sao_hoi": "Hành động không hoàn tác được"},
            )

        return PermissionDecision(DENY, f"UNKNOWN_TOOL · Tool '{tool_name}' không có trong danh sách cho phép.")

    # Giữ API cũ để tương thích
    def check_permission(self, tool_name: str, args: Dict[str, Any]):
        d = self.check(tool_name, args)
        return d.verdict == ALLOW, d.reason
