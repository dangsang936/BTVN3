# -*- coding: utf-8 -*-
"""SE373 · Kiểm căn cứ câu trả lời .

Lưu ý phân biệt: đây KHÔNG phải lớp "ràng buộc là dữ liệu" (xem harness/constraints.py).
Lớp này đối chiếu mọi số liệu, mã, ngày giờ trong câu trả lời với observation của tool và với
chính lời người dùng; dữ kiện không có nguồn thì câu trả lời bị chặn.
Ngoài ra `phat_hien_tuyen_bo_dat_ve` bắt lỗi "Booked!" khi chưa hề có vé trong CSDL.
"""
import re
from typing import Any, Dict, List

# Các mẫu regex trích xuất dữ kiện nghiệp vụ hàng không
MAU_DU_KIEN_HANG_KHONG = [
    r"BK-\d{4,6}",                                      # Mã đặt chỗ: BK-10001
    r"\b(?:VN|VJ|QH)\d{3,4}\b",                         # Mã chuyến bay: VN123, VJ456, QH789
    r"\d{1,3}(?:[.,]\d{3})+(?:\s?đ|\s?VNĐ|\s?đồng)?",   # Số tiền: 1.850.000đ, 1,250,000 VNĐ
    r"\b\d{1,2}:\d{2}\b",                               # Giờ bay: 08:00, 10:15
    r"\b\d{4}-\d{2}-\d{2}\b",                          # Ngày bay chuẩn ISO: 2026-10-15
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",               # Ngày bay định dạng VN: 15/10/2026
    r"\b\d{1,2}[A-F]\b",                               # Số ghế: 12A, 13B
]


def trich_xuat_du_kien(text: str) -> List[str]:
    """Trích xuất tất cả các dữ kiện số liệu, mã định danh từ văn bản."""
    ket_qua = []
    for mau in MAU_DU_KIEN_HANG_KHONG:
        khop = re.findall(mau, text)
        ket_qua.extend(khop)
    # Loại bỏ trùng lặp và giữ nguyên thứ tự xuất hiện
    return list(dict.fromkeys(ket_qua))


def kiem_can_cu_dat_ve(cau_tra_loi: str, ket_qua_tool: List[Any]) -> Dict[str, Any]:
    """Đối chiếu các dữ kiện trong câu trả lời của Agent với kết quả thực tế từ các Tool.
    
    Tham số:
      cau_tra_loi: Nội dung câu trả lời cuối cùng Agent sinh ra cho người dùng.
      ket_qua_tool: Danh sách các nội dung quan sát (observation) đã nhận từ Tool trong phiên.
    
    Trả về dict:
      - dat: True nếu 100% dữ kiện có nguồn gốc từ tool, False nếu có dữ kiện bịa.
      - chi_tiet: Chi tiết từng dữ kiện và cờ co_nguon.
      - khong_co_nguon: Danh sách các dữ kiện không tìm thấy trong dữ liệu tool.
    """
    # Gộp toàn bộ kết quả quan sát thành một chuỗi nguồn
    chuoi_nguon = " ".join(str(x) for x in ket_qua_tool)

    du_kien_tim_thay = trich_xuat_du_kien(cau_tra_loi)
    chi_tiet = []
    khong_co_nguon = []

    for d in du_kien_tim_thay:
        # Chuẩn hóa để so sánh linh hoạt (bỏ dấu chấm/phẩy số tiền hoặc ký hiệu khoảng trắng).
        # Số tiền chỉ so phần số: "1.850.000 đ" phải khớp nguồn "1,850,000 VNĐ" / price_raw 1850000.
        d_cmp = re.sub(r"\s?(?:đồng|VNĐ|đ)$", "", d, flags=re.I)
        d_clean = d_cmp.replace(".", "").replace(",", "").replace(" ", "").upper()
        nguon_clean = chuoi_nguon.replace(".", "").replace(",", "").replace(" ", "").upper()

        # Kiểm tra trực tiếp hoặc sau khi loại bỏ dấu phân cách
        co_nguon = (d in chuoi_nguon) or (d_cmp in chuoi_nguon) or (d_clean in nguon_clean)

        # Hỗ trợ chuẩn hóa ngày bay (ví dụ 15/10/2026 <-> 2026-10-15)
        if not co_nguon and "/" in d:
            parts = d.split("/")
            if len(parts) == 3 and len(parts[2]) == 4:
                iso_date = f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"
                if iso_date in chuoi_nguon or iso_date.replace("-", "") in nguon_clean:
                    co_nguon = True
        elif not co_nguon and "-" in d:
            parts = d.split("-")
            if len(parts) == 3 and len(parts[0]) == 4:
                vn_date = f"{int(parts[2]):02d}/{int(parts[1]):02d}/{parts[0]}"
                if vn_date in chuoi_nguon or vn_date.replace("/", "") in nguon_clean:
                    co_nguon = True

        chi_tiet.append({"du_kien": d, "co_nguon": co_nguon})

        if not co_nguon:
            khong_co_nguon.append(d)

    return {
        "dat": len(khong_co_nguon) == 0,
        "tong_so_du_kien": len(du_kien_tim_thay),
        "so_du_kien_co_nguon": len(du_kien_tim_thay) - len(khong_co_nguon),
        "khong_co_nguon": khong_co_nguon,
        "chi_tiet": chi_tiet,
    }


def chan_truoc_khi_tra_loi(cau_tra_loi: str, ket_qua_tool: List[Any]) -> str:
    """Chặn câu trả lời không có căn cứ, trả về thông điệp an toàn theo nguyên tắc Harness."""
    kiem_tra = kiem_can_cu_dat_ve(cau_tra_loi, ket_qua_tool)
    if kiem_tra["dat"]:
        return cau_tra_loi

    canh_bao = (
        "⚠️ [CẢNH BÁO HARNESS - DỮ KIỆN KHÔNG CĂN CỨ]\n"
        "Câu trả lời bị chặn do chứa thông tin không có trong kết quả trả về của hệ thống vé:\n"
        f"  - Dữ kiện thiếu nguồn: {', '.join(kiem_tra['khong_co_nguon'])}\n"
        "Hệ thống không cho phép phản hồi thông tin chưa được xác thực từ CSDL chuyến bay."
    )
    return canh_bao


_CLAIM_PATTERNS = [
    r"đặt vé thành công", r"đã đặt (?:vé|chỗ|thành công)", r"đã xác nhận đặt", r"mã đặt chỗ (?:của bạn )?là",
    r"\bbooked\b", r"booking (?:is )?confirmed",
]


def phat_hien_tuyen_bo_dat_ve(cau_tra_loi: str) -> bool:
    """True nếu câu trả lời tuyên bố đã đặt vé thành công."""
    t = cau_tra_loi.lower()
    return any(re.search(p, t) for p in _CLAIM_PATTERNS)
