# -*- coding: utf-8 -*-
"""SE373 · Tool mockup cho agent đặt vé (function calling).

Mỗi tool có đủ 3 thành phần tối thiểu của một tool schema: name, description (docstring),
schema tham số (`args_schema` Pydantic trong schemas.py). Model chỉ SINH tool call; ứng dụng
(harness) validate tham số rồi mới thực thi.

Mỗi kết quả tool được dựng qua `ToolResult` (Pydantic) rồi mới serialize -> observation luôn đúng
một định dạng, với `status` thuộc: ok | not_found | invalid_param | error.
"""
from typing import Optional

from langchain_core.tools import tool

from schemas import (BookFlightArgs, BookingCodeArgs, BookingInfo, CancelArgs, FlightDetail, FlightIdArgs,
                     FlightInfo, SearchFlightsArgs, ToolResult)
from tools.mock_database import AIRPORTS, db


def _out(**kw) -> str:
    """Validate observation theo ToolResult trước khi trả cho model."""
    return ToolResult(**kw).model_dump_json(exclude_none=True)


def _fault(tool_name: str) -> Optional[str]:
    kind = db.faults.get(tool_name)
    if kind:
        return _out(status="error", error=kind, hint="Dịch vụ đang lỗi, thử lại sau hoặc bàn giao cho nhân viên.")
    return None


def _flight(fl: dict) -> dict:
    return {
        "flight_id": fl["flight_id"], "airline": fl["airline"], "origin": fl["origin"],
        "destination": fl["destination"], "date": fl["date"], "departure_time": fl["departure_time"],
        "arrival_time": fl["arrival_time"], "price": f"{fl['price']:,} {fl['currency']}",
        "price_raw": fl["price"], "seats_available": fl["seats_available"],
        "availability": "AVAILABLE" if fl["seats_available"] > 0 else "SOLD_OUT",
    }


def _booking(b: dict) -> BookingInfo:
    return BookingInfo(
        booking_code=b["booking_code"], flight_id=b["flight_id"], date=b.get("date"),
        departure_time=b.get("departure_time"), passenger_name=b["passenger_name"],
        seat_number=b["seat_number"], total_amount=f"{b['total_amount']:,} VNĐ",
        total_amount_raw=b["total_amount"], booking_status=b["status"],
    )


@tool(args_schema=SearchFlightsArgs)
def search_flights(origin: str, destination: str, date: str) -> str:
    """Tìm chuyến bay theo điểm đi, điểm đến và ngày bay (YYYY-MM-DD). Trả danh sách chuyến kèm giờ cất cánh, giá (price_raw) và số ghế trống."""
    f = _fault("search_flights")
    if f:
        return f
    orig, dest = db.find_airport_code(origin), db.find_airport_code(destination)
    if not orig or not dest:
        return _out(status="invalid_param", param="origin" if not orig else "destination",
                    hint="Dùng một trong các mã sân bay được hỗ trợ.",
                    supported_airports={c: i["city"] for c, i in AIRPORTS.items()})
    flights = db.search_flights(orig, dest, date)
    if not flights:
        return _out(status="not_found", flights=[], message=f"Không có chuyến {orig} -> {dest} ngày {date}",
                    hint="Thử đổi ngày bay.")
    return _out(status="ok", flights=[FlightInfo(**_flight(x)) for x in flights])


@tool(args_schema=FlightIdArgs)
def get_flight_details(flight_id: str) -> str:
    """Tra cứu chi tiết một chuyến bay theo mã chuyến (ví dụ VN123)."""
    f = _fault("get_flight_details")
    if f:
        return f
    fl = db.get_flight_by_id(flight_id)
    if not fl:
        return _out(status="not_found", message=f"Không tìm thấy chuyến {flight_id}",
                    hint="Gọi search_flights trước để lấy mã chuyến hợp lệ.")
    detail = FlightDetail(**_flight(fl), class_type=fl["class_type"],
                          baggage="23kg ký gửi + 12kg xách tay" if "Vietnam" in fl["airline"] else "7kg xách tay")
    return _out(status="ok", flight=detail)


@tool(args_schema=BookFlightArgs)
def book_flight(flight_id: str, passenger_name: str, passenger_id: str,
                seat_number: Optional[str] = None, user_id: str = "") -> str:
    """Đặt vé chính thức. Cần flight_id lấy từ search_flights, họ tên và CCCD do người dùng cung cấp."""
    f = _fault("book_flight")
    if f:
        return f
    res = db.create_booking(flight_id=flight_id, passenger_name=passenger_name, passenger_id=passenger_id,
                            user_id=user_id, seat_number=seat_number)
    if res["status"] == "error":
        sold_out = res["error_code"] == "SEATS_UNAVAILABLE"
        return _out(status="error", error=res["error_code"], message=res["message"],
                    hint="Chuyến đã hết chỗ: tìm chuyến khác và hỏi lại người dùng." if sold_out
                    else "Kiểm tra lại mã chuyến.")
    return _out(status="ok", message="Đặt vé thành công", booking=_booking(res["booking"]))


@tool(args_schema=BookingCodeArgs)
def check_booking_status(booking_code: str) -> str:
    """Kiểm tra tình trạng một mã đặt chỗ (ví dụ BK-10001)."""
    f = _fault("check_booking_status")
    if f:
        return f
    b = db.get_booking(booking_code)
    if not b:
        return _out(status="not_found", message=f"Không tồn tại mã đặt chỗ {booking_code}",
                    hint="Không được suy đoán thông tin vé; báo người dùng kiểm tra lại mã.")
    return _out(status="ok", booking=_booking(b))


@tool(args_schema=CancelArgs)
def cancel_flight_booking(booking_code: str, user_id: str = "") -> str:
    """Hủy vé theo mã đặt chỗ. Hành động có tác dụng phụ, harness sẽ yêu cầu người duyệt."""
    f = _fault("cancel_flight_booking")
    if f:
        return f
    if not db.get_booking(booking_code):
        return _out(status="not_found", message=f"Không tồn tại mã {booking_code}", hint="Kiểm tra lại mã vé.")
    res = db.cancel_booking(booking_code)
    if res["status"] != "success":
        return _out(status="error", error=res["error_code"], message=res["message"], hint="Vé đã hủy trước đó.")
    return _out(status="ok", message=res["message"], booking=_booking(res["booking"]))


# Tham số mà mỗi tool nhận (dùng để chuyển PlanStep -> tool args)
TOOL_ARG_FIELDS = {
    "search_flights": ["origin", "destination", "date"],
    "get_flight_details": ["flight_id"],
    "book_flight": ["flight_id", "passenger_name", "passenger_id"],
    "check_booking_status": ["booking_code"],
    "cancel_flight_booking": ["booking_code"],
}


def get_flight_tools():
    return [search_flights, get_flight_details, book_flight, check_booking_status, cancel_flight_booking]
