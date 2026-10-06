# -*- coding: utf-8 -*-
"""SE373 · Lớp harness 1: RÀNG BUỘC LÀ DỮ LIỆU.

Yêu cầu của người dùng được ghi thành một đối tượng dữ liệu cố định NGAY TỪ ĐẦU, nằm ngoài
lịch sử hội thoại. Dù lịch sử dài ra và model "quên", harness vẫn kiểm lại:
  - trước book_flight          -> Constraints.check_flight()  (chặn, trả {"status": "denied"})
  - trong tiêu chí hoàn thành  -> Constraints.check_flight()  (vé đã đặt có đúng yêu cầu không)
  - làm đại lượng tiến triển   -> Constraints.score()          (số ràng buộc đã thỏa)

Trích ràng buộc bằng regex (sensor computational: xác định, không tốn token).
"""
import re
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

from tools.mock_database import AIRPORTS

DEFAULT_YEAR = 2026


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


# Các cách viết tên thành phố -> mã IATA (so khớp trên chuỗi đã bỏ dấu)
_CITY_ALIASES = {
    "HAN": ["ha noi", "hanoi"],
    "SGN": ["tp.hcm", "tp hcm", "tphcm", "ho chi minh", "sai gon", "saigon"],
    "DAD": ["da nang", "danang"],
    "CXR": ["nha trang", "cam ranh"],
    "PQC": ["phu quoc"],
    "HPH": ["hai phong"],
}


@dataclass
class Constraints:
    """Ràng buộc của một yêu cầu đặt vé. None = người dùng không đặt ràng buộc đó."""
    intent: str = "unknown"                 # book | search | lookup | cancel | unknown
    origin: Optional[str] = None            # mã IATA
    destination: Optional[str] = None
    date: Optional[str] = None              # YYYY-MM-DD
    depart_after: Optional[str] = None      # "HH:MM", giờ cất cánh >= giá trị này
    depart_before: Optional[str] = None     # "HH:MM", giờ cất cánh <  giá trị này
    max_price: Optional[int] = None         # VNĐ
    flight_id: Optional[str] = None         # người dùng chỉ định đích danh chuyến
    prefer_cheapest: bool = False
    passenger_name: Optional[str] = None
    passenger_id: Optional[str] = None
    booking_code: Optional[str] = None

    # ------------------------------------------------------------------ kiểm tra
    def check_flight(self, flight: Dict[str, Any]) -> List[str]:
        """Trả về danh sách vi phạm (rỗng = chuyến thỏa mọi ràng buộc)."""
        v = []
        dep = flight.get("departure_time", "")
        price = flight.get("price_raw", flight.get("price"))
        if self.flight_id and flight.get("flight_id") != self.flight_id:
            v.append(f"flight_id: người dùng yêu cầu {self.flight_id}, không phải {flight.get('flight_id')}")
        if self.origin and flight.get("origin") != self.origin:
            v.append(f"origin: cần {self.origin}")
        if self.destination and flight.get("destination") != self.destination:
            v.append(f"destination: cần {self.destination}")
        if self.date and flight.get("date") != self.date:
            v.append(f"date: cần {self.date}, chuyến bay ngày {flight.get('date')}")
        if self.depart_after and dep < self.depart_after:
            v.append(f"depart_after: cần cất cánh từ {self.depart_after}, chuyến cất cánh {dep}")
        if self.depart_before and dep >= self.depart_before:
            v.append(f"depart_before: cần cất cánh trước {self.depart_before}, chuyến cất cánh {dep}")
        if self.max_price is not None and isinstance(price, (int, float)) and price > self.max_price:
            v.append(f"max_price: tối đa {self.max_price:,}, giá {int(price):,}")
        return v

    def active(self) -> List[str]:
        """Tên các ràng buộc về chuyến bay đang có hiệu lực."""
        keys = ["flight_id", "origin", "destination", "date", "depart_after", "depart_before", "max_price"]
        return [k for k in keys if getattr(self, k) not in (None, "")]

    def score(self, flight: Optional[Dict[str, Any]]) -> int:
        """Số ràng buộc chuyến bay mà `flight` thỏa (đại lượng tiến triển)."""
        if not flight:
            return 0
        violated = {x.split(":")[0] for x in self.check_flight(flight)}
        return sum(1 for k in self.active() if k not in violated)

    def best_candidate(self, flights: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Chuyến còn chỗ, thỏa mọi ràng buộc; nếu prefer_cheapest thì chọn rẻ nhất."""
        ok = [f for f in flights if f.get("seats_available", 0) > 0 and not self.check_flight(f)]
        if not ok:
            return None
        key = (lambda f: f.get("price_raw", 10**12)) if self.prefer_cheapest else (lambda f: f.get("departure_time", ""))
        return min(ok, key=key)

    def missing_for_booking(self) -> List[str]:
        miss = []
        if not self.passenger_name:
            miss.append("họ tên hành khách")
        if not self.passenger_id:
            miss.append("số CCCD/hộ chiếu")
        return miss

    # ------------------------------------------------------------------ tiện ích
    def merge(self, newer: "Constraints") -> "Constraints":
        """Hội thoại đa lượt: ràng buộc mới (khác None) ghi đè ràng buộc cũ."""
        data = asdict(self)
        for f in fields(newer):
            val = getattr(newer, f.name)
            if f.name == "intent":
                if val != "unknown":
                    data["intent"] = val
            elif f.name == "prefer_cheapest":
                data["prefer_cheapest"] = data["prefer_cheapest"] or val
            elif val not in (None, ""):
                data[f.name] = val
        # Người dùng chỉ định chuyến mới thì bỏ chuyến cũ
        if newer.flight_id:
            data["flight_id"] = newer.flight_id
        return Constraints(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "", False)}

    def describe(self) -> str:
        d = self.to_dict()
        return ", ".join(f"{k}={v}" for k, v in d.items()) or "(chưa có ràng buộc)"

    # ------------------------------------------------------------------ trích xuất
    @classmethod
    def from_request(cls, req) -> "Constraints":
        """Từ BookingRequest (output có cấu trúc của model, đã validate Pydantic + kiểm căn cứ)."""
        d = req.model_dump()
        intent = d["intent"] if d["intent"] != "other" else "unknown"
        return cls(intent=intent, **{k: d[k] for k in (
            "origin", "destination", "date", "depart_after", "depart_before", "max_price", "flight_id",
            "prefer_cheapest", "passenger_name", "passenger_id", "booking_code")})

    @classmethod
    def from_text(cls, text: str) -> "Constraints":
        c = cls()
        raw = text
        t = _strip_accents(text)

        # Ý định
        if re.search(r"\bhuy\b", t):
            c.intent = "cancel"
        elif re.search(r"bk-\d+", t) and re.search(r"kiem tra|tra cuu|xem", t):
            c.intent = "lookup"
        elif re.search(r"(?<!ma )\bdat\b|\bbook\b", t):
            c.intent = "book"
        elif re.search(r"\btim\b|co chuyen|chuyen nao", t):
            c.intent = "search"

        # Mã chuyến / mã vé
        m = re.search(r"\b(VN|VJ|QH)\s?(\d{3,4})\b", raw, re.I)
        if m:
            c.flight_id = (m.group(1) + m.group(2)).upper()
        m = re.search(r"\bBK-\d{4,6}\b", raw, re.I)
        if m:
            c.booking_code = m.group(0).upper()

        # Điểm đi / đến: ưu tiên TỪ KHÓA ("từ X" = điểm đi, "đi/đến/tới/về X" = điểm đến),
        # chỉ khi không có từ khóa mới dựa vào thứ tự xuất hiện (bản trước sai với
        # "VN201 đi Đà Nẵng từ Hà Nội" -> đảo ngược chặng; phát hiện nhờ evaluation KB2).
        hits = []
        for code in AIRPORTS:
            for mm in re.finditer(rf"\b{code}\b", raw):
                hits.append((mm.start(), code))
        for code, aliases in _CITY_ALIASES.items():
            for a in aliases:
                for mm in re.finditer(re.escape(a), t):
                    hits.append((mm.start(), code))
        hits.sort()
        ordered = []
        for _, code in hits:
            if code not in ordered:
                ordered.append(code)
        origin = dest = None
        tl = unicodedata.normalize("NFC", text).lower()      # giữ dấu: "về" khác "vé"
        for pos, code in hits:
            before = tl[max(0, pos - 12):pos]
            if origin is None and re.search(r"\btừ\s*\(?\s*$", before):
                origin = code
            elif dest is None and code != origin and re.search(r"(\bđi|\bđến|\btới|\bvề|\bra|\bvào|->|→|-)\s*\(?\s*$", before):
                dest = code
        rest = [x for x in ordered if x not in (origin, dest)]
        if origin is None and dest is None:
            if len(ordered) >= 2:
                origin, dest = ordered[0], ordered[1]
            elif ordered:
                origin = ordered[0]
        elif origin is None and rest:
            origin = rest[0]
        elif dest is None and rest:
            dest = rest[0]
        c.origin, c.destination = origin, dest

        # Ngày
        m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", raw)
        if m:
            c.date = m.group(0)
        else:
            m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", raw)
            if m:
                y = int(m.group(3) or DEFAULT_YEAR)
                c.date = f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

        # Giờ
        def hhmm(h, mi=None):
            return f"{int(h):02d}:{int(mi or 0):02d}"
        m = re.search(r"truoc\s+(\d{1,2})(?:[:h](\d{2}))?\s*(?:h|gio)?", t)
        if m:
            c.depart_before = hhmm(m.group(1), m.group(2))
        m = re.search(r"(?:sau|tu)\s+(\d{1,2})(?:[:h](\d{2}))?\s*(?:h|gio)", t)
        if m:
            c.depart_after = hhmm(m.group(1), m.group(2))
        if not c.depart_before and not c.depart_after:
            # So trên chuỗi CÒN DẤU: bỏ dấu thì "sang" (đổi sang) trùng "sáng", "tôi" trùng "tối"
            if re.search(r"\bsáng\b", tl):
                c.depart_before = "12:00"
            elif re.search(r"\bchiều\b", tl):
                c.depart_after, c.depart_before = "12:00", "18:00"
            elif re.search(r"\btối\b", tl):
                c.depart_after = "18:00"

        # Giá trần
        m = re.search(r"(?:duoi|toi da|khong qua)\s*([\d.,]+)\s*(trieu|tr|k|nghin)?", t)
        if m:
            num, unit = m.group(1), m.group(2)
            if unit in ("trieu", "tr"):
                c.max_price = int(float(num.replace(",", ".")) * 1_000_000)
            else:
                val = int(num.replace(".", "").replace(",", ""))
                c.max_price = val * 1000 if unit in ("k", "nghin") else val

        if re.search(r"re nhat|gia thap nhat|cheapest", t):
            c.prefer_cheapest = True

        # Hành khách
        m = re.search(r"(?:hành khách|khách|cho)\s+([A-ZÀ-Ỹ][\wÀ-ỹ]*(?:\s+[A-ZÀ-Ỹ][\wÀ-ỹ]*)+)", raw)
        if m:
            c.passenger_name = m.group(1).strip()
        m = re.search(r"(?:CCCD|CMND|hộ chiếu|passport)[\s:]*([A-Z0-9-]{6,})", raw, re.I)
        if m:
            c.passenger_id = m.group(1)
        return c
