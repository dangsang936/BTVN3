# -*- coding: utf-8 -*-
"""SE373 · Lớp harness 4: BÀN GIAO CHO CON NGƯỜI.

Một gói bàn giao tốt trả lời được trong 30 giây:
  - Trạng thái    : đã làm tới đâu, HÀNH ĐỘNG NÀO ĐÃ CÓ TÁC DỤNG PHỤ (vé đã tạo / đã hủy)
  - Những gì đã thử: hướng nào đã hỏng và vì sao
  - Câu hỏi cụ thể : người nhận chỉ cần trả lời có/không hoặc chọn một phương án
"""
from typing import Any, Dict, List, Optional


def tao_ban_giao(
    ly_do: str,
    da_thu: List[str],
    trang_thai: Dict[str, Any],
    cau_hoi: str,
    loai_dung: str = "",
    tac_dung_phu: Optional[List[str]] = None,
    rang_buoc: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "loai_dung": loai_dung,
        "stop_reason": ly_do,
        "rang_buoc": dict(rang_buoc or {}),
        "trang_thai": dict(trang_thai),
        "tac_dung_phu": list(tac_dung_phu or []),
        "da_thu": list(da_thu),
        "cau_hoi_cho_nguoi": cau_hoi,
    }


def dinh_dang_ban_giao(g: Dict[str, Any]) -> str:
    da_thu = "\n".join(f"      {i+1}. {x}" for i, x in enumerate(g.get("da_thu", []))) or "      (chưa có)"
    tdp = ", ".join(g.get("tac_dung_phu", [])) or "Không có (chưa thay đổi CSDL)"
    rb = ", ".join(f"{k}={v}" for k, v in g.get("rang_buoc", {}).items()) or "(trống)"
    tt = ", ".join(f"{k}={v}" for k, v in g.get("trang_thai", {}).items() if v not in (None, "", [])) or "(trống)"
    return "\n".join([
        "┌─ BÀN GIAO CHO NGƯỜI TIẾP QUẢN " + "─" * 46,
        f"│ Kiểu dừng      : {g.get('loai_dung', '')}",
        f"│ Lý do          : {g.get('stop_reason', '')}",
        f"│ Ràng buộc      : {rb}",
        f"│ Trạng thái     : {tt}",
        f"│ Tác dụng phụ   : {tdp}",
        "│ Đã thử         :",
        *[f"│{line}" for line in da_thu.split("\n")],
        f"│ CÂU HỎI        : {g.get('cau_hoi_cho_nguoi', '')}",
        "└" + "─" * 77,
    ])
