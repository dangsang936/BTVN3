# -*- coding: utf-8 -*-
"""Cơ sở dữ liệu giả lập cho hệ thống đặt vé máy bay (Mock Database)."""
import copy
from datetime import datetime
from typing import Any, Dict, List, Optional

# Danh mục sân bay và thành phố
AIRPORTS = {
    "HAN": {"city": "Hà Nội", "name": "Sân bay Quốc tế Nội Bài"},
    "SGN": {"city": "TP. Hồ Chí Minh", "name": "Sân bay Quốc tế Tân Sơn Nhất"},
    "DAD": {"city": "Đà Nẵng", "name": "Sân bay Quốc tế Đà Nẵng"},
    "CXR": {"city": "Nha Trang", "name": "Sân bay Quốc tế Cam Ranh"},
    "PQC": {"city": "Phú Quốc", "name": "Sân bay Quốc tế Phú Quốc"},
    "HPH": {"city": "Hải Phòng", "name": "Sân bay Quốc tế Cát Bi"},
}

# Dữ liệu chuyến bay mặc định
DEFAULT_FLIGHTS = [
    {
        "flight_id": "VN123",
        "airline": "Vietnam Airlines",
        "origin": "HAN",
        "destination": "SGN",
        "date": "2026-10-15",
        "departure_time": "08:00",
        "arrival_time": "10:15",
        "price": 1850000,
        "currency": "VNĐ",
        "seats_available": 8,
        "class_type": "Economy",
    },
    {
        "flight_id": "VJ456",
        "airline": "Vietjet Air",
        "origin": "HAN",
        "destination": "SGN",
        "date": "2026-10-15",
        "departure_time": "11:30",
        "arrival_time": "13:45",
        "price": 1250000,
        "currency": "VNĐ",
        "seats_available": 15,
        "class_type": "Economy",
    },
    {
        "flight_id": "QH789",
        "airline": "Bamboo Airways",
        "origin": "HAN",
        "destination": "SGN",
        "date": "2026-10-15",
        "departure_time": "17:00",
        "arrival_time": "19:15",
        "price": 1600000,
        "currency": "VNĐ",
        "seats_available": 4,
        "class_type": "Economy",
    },
    # Chuyến bay VN201 cố tình HẾT CHỖ (seats_available: 0) để thử nghiệm xử lý bế tắc / tìm chuyến thay thế
    {
        "flight_id": "VN201",
        "airline": "Vietnam Airlines",
        "origin": "HAN",
        "destination": "DAD",
        "date": "2026-10-15",
        "departure_time": "09:00",
        "arrival_time": "10:20",
        "price": 1500000,
        "currency": "VNĐ",
        "seats_available": 0,
        "class_type": "Economy",
    },
    {
        "flight_id": "VJ301",
        "airline": "Vietjet Air",
        "origin": "HAN",
        "destination": "DAD",
        "date": "2026-10-15",
        "departure_time": "14:15",
        "arrival_time": "15:35",
        "price": 1100000,
        "currency": "VNĐ",
        "seats_available": 10,
        "class_type": "Economy",
    },
    {
        "flight_id": "VN502",
        "airline": "Vietnam Airlines",
        "origin": "SGN",
        "destination": "PQC",
        "date": "2026-10-16",
        "departure_time": "07:30",
        "arrival_time": "08:35",
        "price": 1350000,
        "currency": "VNĐ",
        "seats_available": 6,
        "class_type": "Economy",
    },
]

# Dữ liệu đặt vé mẫu sẵn có trong hệ thống
DEFAULT_BOOKINGS = {
    "BK-10001": {
        "booking_code": "BK-10001",
        "flight_id": "VN123",
        "passenger_name": "Tran Thi B",
        "passenger_id": "CCCD-00123456",
        "user_id": "user_customer_1",
        "seat_number": "12A",
        "total_amount": 1850000,
        "status": "CONFIRMED",
        "created_at": "2026-09-20 14:00:00",
    }
}

# Dữ liệu phân quyền người dùng
USERS = {
    # budget_limit      : trần cứng, vượt là TỪ CHỐI.
    # approval_threshold: vượt ngưỡng này thì phải CHỜ NGƯỜI DUYỆT (điều kiện dừng 5 trong slide).
    "guest_01": {"role": "guest", "name": "Khách Vãng Lai", "budget_limit": 0, "approval_threshold": 0},
    "user_customer_1": {"role": "customer", "name": "Nguyen Van A", "budget_limit": 10000000, "approval_threshold": 1500000},
    "admin_root": {"role": "admin", "name": "Quản Trị Viên", "budget_limit": 100000000, "approval_threshold": 50000000},
}


class MockFlightDatabase:
    """CSDL quản lý trạng thái chuyến bay và đặt chỗ trong bộ nhớ."""

    def __init__(self):
        self.flights: List[Dict[str, Any]] = copy.deepcopy(DEFAULT_FLIGHTS)
        self.bookings: Dict[str, Dict[str, Any]] = copy.deepcopy(DEFAULT_BOOKINGS)
        self._next_booking_id: int = 10002
        # Tiêm lỗi để mô phỏng tool hỏng: {"search_flights": "timeout"} làm tool trả lỗi timeout.
        self.faults: Dict[str, str] = {}

    def reset(self):
        """Khôi phục CSDL về trạng thái ban đầu (xóa cả lỗi đã tiêm)."""
        self.flights = copy.deepcopy(DEFAULT_FLIGHTS)
        self.bookings = copy.deepcopy(DEFAULT_BOOKINGS)
        self._next_booking_id = 10002
        self.faults = {}

    def find_airport_code(self, location_query: str) -> Optional[str]:
        """Chuẩn hóa tên thành phố / mã sân bay thành mã IATA 3 ký tự."""
        q = location_query.strip().upper()
        if q in AIRPORTS:
            return q
        q_lower = location_query.strip().lower()
        for code, info in AIRPORTS.items():
            if (
                q_lower in info["city"].lower()
                or info["city"].lower() in q_lower
                or q_lower in info["name"].lower()
            ):
                return code
        return None

    def search_flights(
        self, origin: str, destination: str, date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Tìm kiếm chuyến bay theo điểm đi, điểm đến và ngày bay."""
        orig_code = self.find_airport_code(origin) or origin.upper()
        dest_code = self.find_airport_code(destination) or destination.upper()

        results = []
        for f in self.flights:
            if f["origin"] == orig_code and f["destination"] == dest_code:
                if date is None or f["date"] == date:
                    results.append(copy.deepcopy(f))
        return results

    def get_flight_by_id(self, flight_id: str) -> Optional[Dict[str, Any]]:
        """Lấy chi tiết một chuyến bay theo mã định danh."""
        fid = flight_id.strip().upper()
        for f in self.flights:
            if f["flight_id"] == fid:
                return copy.deepcopy(f)
        return None

    def create_booking(
        self,
        flight_id: str,
        passenger_name: str,
        passenger_id: str,
        user_id: str = "user_customer_1",
        seat_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Tạo đặt chỗ mới và trừ số lượng ghế còn lại."""
        fid = flight_id.strip().upper()
        flight = None
        for f in self.flights:
            if f["flight_id"] == fid:
                flight = f
                break

        if not flight:
            return {"status": "error", "error_code": "FLIGHT_NOT_FOUND", "message": f"Không tìm thấy chuyến bay {flight_id}"}

        if flight["seats_available"] <= 0:
            return {"status": "error", "error_code": "SEATS_UNAVAILABLE", "message": f"Chuyến bay {flight_id} đã hết chỗ"}

        # Giảm số ghế
        flight["seats_available"] -= 1

        booking_code = f"BK-{self._next_booking_id}"
        self._next_booking_id += 1

        auto_seat = seat_number or f"{10 + (self._next_booking_id % 20)}{chr(65 + (self._next_booking_id % 6))}"

        record = {
            "booking_code": booking_code,
            "flight_id": flight["flight_id"],
            "airline": flight["airline"],
            "origin": flight["origin"],
            "destination": flight["destination"],
            "date": flight["date"],
            "departure_time": flight["departure_time"],
            "passenger_name": passenger_name,
            "passenger_id": passenger_id,
            "user_id": user_id,
            "seat_number": auto_seat,
            "total_amount": flight["price"],
            "status": "CONFIRMED",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        self.bookings[booking_code] = record
        return {"status": "success", "booking": copy.deepcopy(record)}

    def get_booking(self, booking_code: str) -> Optional[Dict[str, Any]]:
        """Lấy thông tin đặt chỗ."""
        code = booking_code.strip().upper()
        return copy.deepcopy(self.bookings.get(code))

    def cancel_booking(self, booking_code: str) -> Dict[str, Any]:
        """Hủy đặt chỗ và hoàn lại số lượng ghế."""
        code = booking_code.strip().upper()
        if code not in self.bookings:
            return {"status": "error", "error_code": "BOOKING_NOT_FOUND", "message": f"Không tìm thấy mã đặt chỗ {booking_code}"}

        booking = self.bookings[code]
        if booking["status"] == "CANCELLED":
            return {"status": "error", "error_code": "ALREADY_CANCELLED", "message": f"Mã đặt chỗ {booking_code} đã bị hủy trước đó"}

        booking["status"] = "CANCELLED"

        # Hoàn lại ghế cho chuyến bay
        for f in self.flights:
            if f["flight_id"] == booking["flight_id"]:
                f["seats_available"] += 1
                break

        return {"status": "success", "message": f"Hủy thành công mã đặt chỗ {booking_code}", "booking": copy.deepcopy(booking)}


# Biến CSDL singleton dùng chung
db = MockFlightDatabase()
