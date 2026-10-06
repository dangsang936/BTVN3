# -*- coding: utf-8 -*-
"""Schema Pydantic cho MỌI dữ liệu đi vào / đi ra model .

Nguyên tắc:
  - KHÔNG:  model -> prose -> đoán kiểu -> code
  - NÊN:    model -> dữ liệu có cấu trúc -> code
  - `Literal` (enum) thu hẹp tập giá trị hợp lệ; field không có default là `required`;
    `extra="forbid"` tương đương `additionalProperties: false` (từ chối field không khai báo).
  - Schema luôn có TRẠNG THÁI HỢP LỆ cho trường hợp thiếu dữ liệu (`insufficient_data`,
    `needs_user_input`, `out_of_scope`) để model không bị ép phải bịa.
  - Schema chỉ kiểm CẤU TRÚC. Tính đúng của NỘI DUNG (mã vé có thật không, chuyến có trong
    kết quả tool không) được harness kiểm riêng: xem harness/output_validator.py.

Nhóm schema:
  1. BookingRequest  · model trích yêu cầu người dùng thành dữ liệu (ràng buộc)
  2. Plan / PlanStep · planner sinh kế hoạch
  3. FinalAnswer     · câu trả lời cuối cho người dùng
  4. *Args           · schema tham số của tool (function calling). Field danh tính (user_id) được
                       đánh dấu InjectedToolArg nên bị ẩn khỏi tool schema gửi cho model.
  5. *Result         · schema kết quả tool (observation)
"""
from datetime import date as _date
from typing import Annotated, List, Literal, Optional

from langchain_core.tools import InjectedToolArg

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AirportCode = Literal["HAN", "SGN", "DAD", "CXR", "PQC", "HPH"]
ToolName = Literal["search_flights", "get_flight_details", "book_flight", "check_booking_status",
                   "cancel_flight_booking"]

DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
TIME_RE = r"^([01]\d|2[0-3]):[0-5]\d$"
FLIGHT_RE = r"^(VN|VJ|QH)\d{3,4}$"
BOOKING_RE = r"^BK-\d{4,6}$"
PAX_ID_RE = r"^[A-Z0-9-]{6,20}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _check_real_date(v: Optional[str]) -> Optional[str]:
    if v is not None:
        _date.fromisoformat(v)          # 2026-02-30 đúng regex nhưng không phải ngày thật
    return v


# =============================================================== 1. Trích yêu cầu
class BookingRequest(Strict):
    """Yêu cầu của người dùng dưới dạng dữ liệu. Field nào người dùng KHÔNG nói thì để null."""
    status: Literal["ready", "insufficient_data", "out_of_scope"] = Field(
        description="ready: đủ dữ liệu để xử lý; insufficient_data: thiếu thông tin bắt buộc; "
                    "out_of_scope: không liên quan tới vé máy bay")
    intent: Literal["book", "search", "lookup", "cancel", "other"]
    origin: Optional[AirportCode] = Field(None, description="Mã IATA điểm đi")
    destination: Optional[AirportCode] = Field(None, description="Mã IATA điểm đến")
    date: Optional[str] = Field(None, pattern=DATE_RE, description="YYYY-MM-DD; năm mặc định 2026")
    depart_after: Optional[str] = Field(None, pattern=TIME_RE, description="HH:MM")
    depart_before: Optional[str] = Field(None, pattern=TIME_RE, description="HH:MM")
    max_price: Optional[int] = Field(None, ge=0, description="Giá trần, đơn vị VNĐ")
    flight_id: Optional[str] = Field(None, pattern=FLIGHT_RE)
    prefer_cheapest: bool = False
    passenger_name: Optional[str] = Field(None, min_length=2, max_length=80)
    passenger_id: Optional[str] = Field(None, pattern=PAX_ID_RE, description="Số CCCD / hộ chiếu")
    booking_code: Optional[str] = Field(None, pattern=BOOKING_RE)
    missing_fields: List[str] = Field(default_factory=list, description="Thông tin bắt buộc còn thiếu")

    @field_validator("date")
    @classmethod
    def _real_date(cls, v):
        return _check_real_date(v)

    @model_validator(mode="after")
    def _rules(self):
        if self.origin and self.destination and self.origin == self.destination:
            raise ValueError("origin và destination không được trùng nhau")
        if self.depart_after and self.depart_before and self.depart_after >= self.depart_before:
            raise ValueError("depart_after phải nhỏ hơn depart_before")
        if self.status == "insufficient_data" and not self.missing_fields:
            raise ValueError("status=insufficient_data thì phải liệt kê missing_fields")
        return self


# =============================================================== 2. Kế hoạch
class PlanStep(Strict):
    """Một bước gọi tool. Chỉ điền tham số mà tool đó dùng, còn lại để null.
    Dùng "$BEST_FLIGHT" cho flight_id khi cần chuyến tốt nhất từ kết quả tìm kiếm trước,
    "$LAST_BOOKING" cho booking_code khi cần mã vé vừa tạo."""
    step_id: int = Field(ge=1)
    tool: ToolName
    origin: Optional[str] = None
    destination: Optional[str] = None
    date: Optional[str] = None
    flight_id: Optional[str] = None
    passenger_name: Optional[str] = None
    passenger_id: Optional[str] = None
    booking_code: Optional[str] = None
    objective: str = Field(min_length=3, description="Mục đích của bước, một câu")

    def tool_args(self) -> dict:
        from tools.tools import TOOL_ARG_FIELDS
        return {k: getattr(self, k) for k in TOOL_ARG_FIELDS[self.tool] if getattr(self, k) is not None}


class Plan(Strict):
    status: Literal["ready", "needs_user_input", "out_of_scope"]
    steps: List[PlanStep] = Field(default_factory=list, max_length=6)
    question_for_user: Optional[str] = None

    @model_validator(mode="after")
    def _rules(self):
        ids = [s.step_id for s in self.steps]
        if ids != list(range(1, len(ids) + 1)):
            raise ValueError("step_id phải liên tiếp từ 1")
        if self.status == "ready" and not self.steps:
            raise ValueError("status=ready thì phải có ít nhất một bước")
        if self.status == "needs_user_input" and not self.question_for_user:
            raise ValueError("status=needs_user_input thì phải có question_for_user")
        return self


# =============================================================== 3. Câu trả lời cuối
class FinalAnswer(Strict):
    """Câu trả lời cuối cho người dùng. Chỉ điền mã/chuyến xuất hiện trong kết quả tool."""
    status: Literal["booked", "options_found", "info", "needs_user_input", "not_found",
                    "denied", "error", "out_of_scope"]
    message: str = Field(min_length=1, max_length=1500, description="Câu trả lời tiếng Việt cho người dùng")
    booking_code: Optional[str] = Field(None, pattern=BOOKING_RE)
    flight_id: Optional[str] = Field(None, pattern=FLIGHT_RE)
    suggested_flight_ids: List[str] = Field(default_factory=list, max_length=5)
    question_for_user: Optional[str] = None

    @field_validator("suggested_flight_ids")
    @classmethod
    def _ids(cls, v):
        import re
        bad = [x for x in v if not re.match(FLIGHT_RE, x)]
        if bad:
            raise ValueError(f"mã chuyến sai định dạng: {bad}")
        return v

    @model_validator(mode="after")
    def _rules(self):
        if self.status == "booked" and not (self.booking_code and self.flight_id):
            raise ValueError("status=booked thì phải có booking_code và flight_id")
        if self.status == "options_found" and not self.suggested_flight_ids:
            raise ValueError("status=options_found thì phải có suggested_flight_ids")
        if self.status == "needs_user_input" and not self.question_for_user:
            raise ValueError("status=needs_user_input thì phải có question_for_user")
        return self


# =============================================================== 4. Tham số tool
class SearchFlightsArgs(Strict):
    origin: str = Field(min_length=2, description="Mã sân bay (HAN, SGN, DAD...) hoặc tên thành phố")
    destination: str = Field(min_length=2, description="Mã sân bay hoặc tên thành phố")
    date: str = Field(pattern=DATE_RE, description="Ngày bay YYYY-MM-DD, ví dụ 2026-10-15")

    @field_validator("date")
    @classmethod
    def _real_date(cls, v):
        return _check_real_date(v)


class FlightIdArgs(Strict):
    flight_id: str = Field(pattern=FLIGHT_RE, description="Mã chuyến, ví dụ VN123")


class BookFlightArgs(Strict):
    flight_id: str = Field(pattern=FLIGHT_RE, description="Mã chuyến lấy từ kết quả search_flights")
    passenger_name: str = Field(min_length=2, description="Họ tên hành khách do người dùng cung cấp")
    passenger_id: str = Field(pattern=PAX_ID_RE, description="Số CCCD/hộ chiếu do người dùng cung cấp")
    seat_number: Optional[str] = Field(None, pattern=r"^\d{1,2}[A-F]$")
    # InjectedToolArg: field KHÔNG có trong tool schema gửi cho model (model không nhìn thấy, không sinh được);
    # harness tự điền danh tính đăng nhập trước khi thực thi -> model không có thêm quyền chỉ vì sinh tool call.
    user_id: Annotated[str, InjectedToolArg] = Field("", description="Do harness điền")


class BookingCodeArgs(Strict):
    booking_code: str = Field(pattern=BOOKING_RE, description="Mã đặt chỗ, ví dụ BK-10001")


class CancelArgs(BookingCodeArgs):
    # InjectedToolArg: field KHÔNG có trong tool schema gửi cho model (model không nhìn thấy, không sinh được);
    # harness tự điền danh tính đăng nhập trước khi thực thi -> model không có thêm quyền chỉ vì sinh tool call.
    user_id: Annotated[str, InjectedToolArg] = Field("", description="Do harness điền")


# =============================================================== 5. Kết quả tool
ToolStatus = Literal["ok", "not_found", "invalid_param", "error"]


class FlightInfo(Strict):
    flight_id: str = Field(pattern=FLIGHT_RE)
    airline: str
    origin: AirportCode
    destination: AirportCode
    date: str = Field(pattern=DATE_RE)
    departure_time: str = Field(pattern=TIME_RE)
    arrival_time: str = Field(pattern=TIME_RE)
    price: str
    price_raw: int = Field(ge=0)
    seats_available: int = Field(ge=0)
    availability: Literal["AVAILABLE", "SOLD_OUT"]


class FlightDetail(FlightInfo):
    class_type: str
    baggage: str


class BookingInfo(Strict):
    booking_code: str = Field(pattern=BOOKING_RE)
    flight_id: str = Field(pattern=FLIGHT_RE)
    date: Optional[str] = None
    departure_time: Optional[str] = None
    passenger_name: str
    seat_number: str
    total_amount: str
    total_amount_raw: int = Field(ge=0)
    booking_status: Literal["CONFIRMED", "CANCELLED"]


class ToolResult(Strict):
    """Observation chuẩn: luôn có status rõ ràng; lỗi luôn kèm hint chỉ đường đi khác."""
    status: ToolStatus
    message: Optional[str] = None
    error: Optional[str] = None
    param: Optional[str] = None
    hint: Optional[str] = None
    flights: Optional[List[FlightInfo]] = None
    flight: Optional[FlightDetail] = None
    booking: Optional[BookingInfo] = None
    supported_airports: Optional[dict] = None

    @model_validator(mode="after")
    def _rules(self):
        if self.status in ("invalid_param", "error") and not self.hint:
            raise ValueError("observation lỗi phải có hint")
        if self.status == "invalid_param" and not self.param:
            raise ValueError("invalid_param phải chỉ ra param sai")
        return self
