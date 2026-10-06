# -*- coding: utf-8 -*-
"""SE373 · Lớp harness 2: TIÊU CHÍ HOÀN THÀNH KIỂM BẰNG CODE.

"Đã xong" không phải do model tự tuyên bố mà do code đọc lại CSDL (kiểm chứng chéo):

    booking = db.get_booking(code)               # đọc lại, không tin observation cũ
    booking.status == "CONFIRMED"
    and booking.user_id == tài khoản đăng nhập
    and Constraints.check_flight(flight) == []   # đúng ngày, giờ, giá trần, chặng, chuyến
    and tên + CCCD khớp ràng buộc
    and booking.total_amount == flight.price     # giá khớp giá niêm yết
    and (không yêu cầu rẻ nhất  or  là chuyến rẻ nhất thỏa ràng buộc)

Harness dùng kết quả này làm ĐIỀU KIỆN DỪNG "đạt mục tiêu" ngay sau observation của book_flight,
và để chặn câu trả lời tuyên bố "đã đặt" khi CSDL nói chưa.
"""
from typing import Any, Dict, List, Optional

from harness.constraints import Constraints
from tools.mock_database import db

CRITERIA = ["booking_exists", "status_confirmed", "owner_match", "constraints_ok",
            "passenger_match", "price_consistent", "cheapest_ok"]


class FlightCompletionChecker:

    @staticmethod
    def _empty(reason: str, applicable: bool = True) -> Dict[str, Any]:
        return {"ap_dung": applicable, "hoan_thanh": False, "ly_do": reason,
                "tieu_chi": {k: False for k in CRITERIA}, "vi_pham": [], "thong_tin_dat_ve": None}

    def check(self, constraints: Constraints, session_booking_codes: List[str],
              user_id: str) -> Dict[str, Any]:
        if constraints.intent != "book":
            return self._empty(f"KHONG_AP_DUNG · Ý định '{constraints.intent}' không phải đặt vé.",
                               applicable=False)
        if not session_booking_codes:
            return self._empty("CHUA_CO_VE · Phiên này chưa tạo vé nào trong CSDL.")

        booking = db.get_booking(session_booking_codes[-1])          # đọc lại CSDL
        if not booking:
            return self._empty("KHONG_TIM_THAY_VE · Mã vé trong observation không có trong CSDL.")

        flight = db.get_flight_by_id(booking["flight_id"]) or {}
        flight_view = {**flight, "price_raw": flight.get("price")}
        violations = constraints.check_flight(flight_view)

        name_ok = (not constraints.passenger_name or
                   constraints.passenger_name.strip().lower() == booking["passenger_name"].strip().lower())
        id_ok = (not constraints.passenger_id or constraints.passenger_id == booking["passenger_id"])

        cheapest_ok = True
        if constraints.prefer_cheapest:
            pool = [f for f in db.flights
                    if not constraints.check_flight({**f, "price_raw": f["price"]})
                    and (f["seats_available"] > 0 or f["flight_id"] == booking["flight_id"])]
            if pool:
                cheapest_ok = booking["total_amount"] <= min(f["price"] for f in pool)

        t = {
            "booking_exists": True,
            "status_confirmed": booking["status"] == "CONFIRMED",
            "owner_match": booking["user_id"] == user_id,
            "constraints_ok": not violations,
            "passenger_match": name_ok and id_ok,
            "price_consistent": bool(flight) and booking["total_amount"] == flight.get("price"),
            "cheapest_ok": cheapest_ok,
        }
        done = all(t.values())
        return {
            "ap_dung": True,
            "hoan_thanh": done,
            "ly_do": "HOAN_THANH_HOP_LE" if done else
                     "VI_PHAM_TIEU_CHI · " + ", ".join(k for k, v in t.items() if not v),
            "tieu_chi": t,
            "vi_pham": violations,
            "thong_tin_dat_ve": booking,
        }
