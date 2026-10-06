# -*- coding: utf-8 -*-
"""Hiển thị kết quả agent trên terminal: bố cục theo khối, căn cột, có màu (tự tắt khi không hỗ trợ).

Mỗi lượt được in theo đúng thứ tự xử lý của harness:

    ╭─ LƯỢT n · mẫu · tài khoản ──────────────────────────╮
    │ 1. YÊU CẦU      ràng buộc do bước extract tạo ra      │
    │ 2. DIỄN BIẾN    plan -> tool_call -> tool_result      │
    │ 3. TRẢ LỜI      FinalAnswer (đã qua kiểm)             │
    │ 4. KIỂM TRA     schema, căn cứ, kiểu dừng, tiêu chí   │
    │ 5. BÀN GIAO     (chỉ khi harness dừng cần người)      │
    │    CHỈ SỐ       LLM · tool · token · chi phí · giây   │

Khung chỉ có viền trái nên tiếng Việt / ký tự rộng không làm lệch viền.
Tắt màu: đặt biến môi trường NO_COLOR=1.
"""
import json
import os
import sys
from typing import Any, Dict, List

W = 78

# ------------------------------------------------------------------ màu
def _color_supported() -> bool:
    if os.getenv("NO_COLOR") or not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        os.system("")                     # bật xử lý mã ANSI trên Windows console
    return True


_COLOR = _color_supported()
_CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34",
          "magenta": "35", "cyan": "36", "gray": "90"}


def c(text: Any, *styles: str) -> str:
    if not _COLOR or not styles:
        return str(text)
    return "\033[" + ";".join(_CODES[s] for s in styles) + "m" + str(text) + "\033[0m"


# ------------------------------------------------------------------ khối
def rule(char: str = "─", style: str = "gray") -> str:
    return c(char * W, style)


def banner(title: str, subtitle: str = "") -> None:
    print(c("═" * W, "cyan"))
    print(c(f"  {title}", "bold", "cyan"))
    if subtitle:
        print(c(f"  {subtitle}", "gray"))
    print(c("═" * W, "cyan"))


def section(title: str, style: str = "cyan") -> None:
    head = f"╭─ {title} "
    print(c(head + "─" * max(0, W - len(head)), style))


def line(text: str = "", indent: int = 0) -> None:
    print(c("│", "gray") + " " + " " * indent + text)


def end() -> None:
    print(c("╰" + "─" * (W - 1), "gray"))


LABEL_W = 16


def kv(label: str, value: Any, width: int = LABEL_W, indent: int = 0, style: str = "") -> None:
    """Một dòng 'nhãn  giá trị'; giá trị dài tự xuống dòng và thẳng cột với dòng đầu."""
    text = str(value)
    plain = "\x1b" in text                       # đã có mã màu -> không cắt dòng
    chunks = [text] if plain else wrap(text, W - 4 - indent - width)
    for i, chunk in enumerate(chunks):
        val = c(chunk, style) if style else chunk
        lab = c(f"{label:<{width}}", "gray") if i == 0 else " " * width
        line(lab + " " + val, indent)


def wrap(text: str, width: int) -> List[str]:
    out, cur = [], ""
    for word in str(text).split():
        if cur and len(cur) + 1 + len(word) > width:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    return out + ([cur] if cur else []) or [""]


def para(text: str, indent: int = 0, style: str = "") -> None:
    for t in str(text).splitlines() or [""]:
        for w in wrap(t, W - 4 - indent):
            line(c(w, style) if style else w, indent)


# ------------------------------------------------------------------ định dạng dữ liệu
def money(v: Any) -> str:
    try:
        return f"{int(v):,}".replace(",", ".") + " đ"
    except (TypeError, ValueError):
        return str(v)


def fmt_args(args: Dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in (args or {}).items() if k != "user_id")


STATUS_STYLE = {
    "ok": "green", "booked": "green", "info": "green", "options_found": "green",
    "not_found": "yellow", "needs_user_input": "yellow", "pending_approval": "yellow", "out_of_scope": "yellow",
    "invalid_param": "red", "denied": "red", "error": "red", "blocked": "red", "rejected_by_human": "red",
}


def badge(status: str) -> str:
    return c(f"[{status}]", STATUS_STYLE.get(status, "blue"), "bold")


CONSTRAINT_LABELS = [
    ("intent", "Ý định"), ("route", "Chặng bay"), ("date", "Ngày bay"), ("time", "Khung giờ"),
    ("max_price", "Giá tối đa"), ("prefer_cheapest", "Ưu tiên"), ("flight_id", "Chuyến chỉ định"),
    ("passenger", "Hành khách"), ("booking_code", "Mã đặt chỗ"), ("con_thieu", "Còn thiếu"),
]


def constraint_rows(d: Dict[str, Any]) -> List[tuple]:
    rows = {"intent": d.get("intent")}
    if d.get("origin") or d.get("destination"):
        rows["route"] = f"{d.get('origin', '?')} → {d.get('destination', '?')}"
    rows["date"] = d.get("date")
    if d.get("depart_after") or d.get("depart_before"):
        rows["time"] = f"{d.get('depart_after', '00:00')} – {d.get('depart_before', '23:59')}"
    if d.get("max_price"):
        rows["max_price"] = money(d["max_price"])
    if d.get("prefer_cheapest"):
        rows["prefer_cheapest"] = "rẻ nhất"
    rows["flight_id"] = d.get("flight_id")
    if d.get("passenger_name") or d.get("passenger_id"):
        rows["passenger"] = f"{d.get('passenger_name', '?')} · CCCD {d.get('passenger_id', '?')}"
    rows["booking_code"] = d.get("booking_code")
    if d.get("con_thieu"):
        rows["con_thieu"] = ", ".join(d["con_thieu"])
    return [(label, rows[k]) for k, label in CONSTRAINT_LABELS if rows.get(k)]


def summarize_observation(obs: str) -> List[str]:
    """Tóm tắt kết quả tool thành vài dòng dễ đọc (dữ liệu gốc vẫn nằm trong steps_log)."""
    try:
        o = json.loads(obs)
    except Exception:
        return [obs[:W - 10]]
    st = o.get("status", "?")
    out = []
    if o.get("flights") is not None:
        fl = o["flights"]
        out.append(f"{badge(st)} {len(fl)} chuyến")
        for f in fl:
            seat = c("hết chỗ", "red") if f.get("seats_available", 0) == 0 else f"còn {f['seats_available']} ghế"
            out.append(f"  {f['flight_id']:<7} {f['departure_time']}–{f['arrival_time']}  "
                       f"{money(f.get('price_raw')):>12}  {seat}")
    elif o.get("flight"):
        f = o["flight"]
        out.append(f"{badge(st)} {f['flight_id']} {f['origin']}→{f['destination']} {f['date']} "
                   f"{f['departure_time']} · {money(f.get('price_raw'))} · còn {f['seats_available']} ghế")
    elif o.get("booking"):
        b = o["booking"]
        out.append(f"{badge(st)} {b['booking_code']} · {b['flight_id']} · ghế {b['seat_number']} · "
                   f"{money(b.get('total_amount_raw'))} · {b['booking_status']}")
    else:
        msg = o.get("message") or o.get("reason") or o.get("error") or ""
        out.append(f"{badge(st)} {msg}".rstrip())
    for v in o.get("violations") or []:
        out.append(c(f"  ✗ {v}", "red"))
    if o.get("hint") and st != "ok":
        out.append(c(f"  gợi ý: {o['hint']}", "gray"))
    return out


# ------------------------------------------------------------------ các khối của một lượt
def show_request(steps: List[Dict[str, Any]], res: Dict[str, Any]) -> None:
    ex = next((s for s in steps if s.get("type") == "extract"), {})
    section("1. YÊU CẦU (ràng buộc dạng dữ liệu)")
    src = {"llm": "model (structured output)", "regex": "regex", "regex_fallback": "regex (model lỗi schema)"}
    kv("Nguồn trích", src.get(ex.get("source"), ex.get("source", "?")))
    for label, val in constraint_rows(ex.get("constraints") or res.get("constraints") or {}):
        kv(label, val, style="red" if label == "Còn thiếu" else "")
    if ex.get("dropped_ungrounded"):
        kv("Bỏ (không căn cứ)", ", ".join(ex["dropped_ungrounded"]), style="yellow")
    end()


def show_trace(steps: List[Dict[str, Any]]) -> None:
    section("2. DIỄN BIẾN  (tool_call → app kiểm & thực thi → tool_result)")
    n = 0
    shown = False
    for st in steps:
        t = st.get("type")
        if t in ("plan", "replan"):
            shown = True
            p = st["plan"]
            title = "Kế hoạch" if t == "plan" else f"Lập lại kế hoạch #{st.get('version')}"
            line(c(f"▸ {title}", "magenta", "bold") + c(f"  status={p.get('status')}", "gray"))
            if st.get("trigger"):
                line(c(f"lý do: {st['trigger']}", "gray"), 2)
            for x in p.get("steps", []):
                args = {k: v for k, v in x.items() if k not in ("step_id", "tool", "objective")}
                line(f"{x['step_id']}. {c(x['tool'], 'bold')}({fmt_args(args)})", 2)
            if p.get("question_for_user"):
                line(c(f"? {p['question_for_user']}", "yellow"), 2)
        elif t == "tool_call":
            shown = True
            n += 1
            cid = c(f"  #{st['call_id']}", "gray") if st.get("call_id") else ""
            head = c(f"▸ [{n}] ", "blue", "bold") + c(st["tool"], "bold")
            args = fmt_args(st["args"])
            plain_len = len(f"▸ [{n}] {st['tool']}({args})  #{st.get('call_id', '')}")
            if plain_len <= W - 3:
                line(head + f"({args})" + cid)
            else:                                   # tham số dài: mỗi tham số một dòng
                line(head + cid)
                for k, v in (st["args"] or {}).items():
                    if k != "user_id":
                        line(c(f"{k} = ", "gray") + str(v), 6)
        elif t == "observation":
            for i, s in enumerate(summarize_observation(st["observation"])):
                line(("↳ " if i == 0 else "  ") + s, 4)
        elif t == "format_error":
            shown = True
            line(c(f"⚠ Sai định dạng: {st.get('errors') or st.get('content')}", "yellow"))
    if not shown:
        line(c("(không gọi tool nào)", "gray"))
    end()


def show_answer(res: Dict[str, Any]) -> None:
    a = res["answer"]
    replaced = res["answer_validation"]["replaced_by_harness"]
    section("3. TRẢ LỜI" + ("  (harness đã thay câu trả lời của model)" if replaced else ""),
            "yellow" if replaced else "green")
    line(badge(a["status"]) + (c(f"  vé {a['booking_code']}", "bold") if a.get("booking_code") else "")
         + (c(f"  chuyến {a['flight_id']}", "bold") if a.get("flight_id") else ""))
    para(a["message"])
    if a.get("suggested_flight_ids"):
        kv("Gợi ý chuyến", ", ".join(a["suggested_flight_ids"]))
    if a.get("question_for_user"):
        line(c("❓ " + a["question_for_user"], "yellow", "bold"))
    end()


def _tick(ok: bool) -> str:
    return c("✓", "green") if ok else c("✗", "red")


def show_checks(res: Dict[str, Any]) -> None:
    v, stop, comp, m = res["answer_validation"], res["stop"], res["completion_report"], res["metrics"]
    section("4. KIỂM TRA CỦA HARNESS")
    kv("Schema", f"{_tick(True)} FinalAnswer hợp lệ · sai schema {m['schema_failures']} lần")
    kv("Nội dung", f"{_tick(not v['semantic_errors'])} " + ("; ".join(v["semantic_errors"]) or "khớp kết quả tool"))
    kv("Căn cứ dữ liệu", f"{_tick(v['grounding_ok'])} " + ("đạt" if v["grounding_ok"] else "KHÔNG đạt"))
    kv("Kiểu dừng", c(stop["kind"], "green" if stop["normal"] else "red", "bold")
       + c(f"  ({'bình thường' if stop['normal'] else 'bất thường'})", "gray"))
    if stop["reason"]:
        kv("", stop["reason"], style="gray")
    if comp["ap_dung"]:
        kv("Hoàn thành", f"{_tick(comp['hoan_thanh'])} {comp['ly_do']}")
        if comp["tieu_chi"].get("booking_exists"):          # chỉ liệt kê tiêu chí khi đã có vé để kiểm
            items = list(comp["tieu_chi"].items())
            for i in range(0, len(items), 3):
                line("   ".join(f"{_tick(ok)} {k:<17}" for k, ok in items[i:i + 3]), LABEL_W + 1)
    else:
        kv("Hoàn thành", c("không áp dụng (không phải đặt vé)", "gray"))
    if res.get("interventions"):
        kv("Can thiệp", ", ".join(i["kind"] for i in res["interventions"]), style="yellow")
    end()


def show_handoff(g: Dict[str, Any]) -> None:
    section("5. BÀN GIAO CHO NGƯỜI TIẾP QUẢN", "yellow")
    kv("Kiểu dừng", g.get("loai_dung", ""))
    kv("Lý do", g.get("stop_reason", ""))
    tt = {k: v for k, v in (g.get("trang_thai") or {}).items() if v not in (None, "", [])}
    kv("Trạng thái", ", ".join(f"{k}={v}" for k, v in tt.items()) or "(trống)")
    kv("Tác dụng phụ", ", ".join(g.get("tac_dung_phu") or []) or "không (CSDL chưa đổi)",
       style="red" if g.get("tac_dung_phu") else "")
    tried = g.get("da_thu") or []
    kv("Đã thử", f"{len(tried)} hành động" if tried else "(chưa có)")
    for i, x in enumerate(tried, 1):
        for j, w in enumerate(wrap(x, W - 8)):
            line((c(f"{i}. ", "gray") if j == 0 else "   ") + w, 2)
    line(c("❓ " + (g.get("cau_hoi_cho_nguoi") or ""), "yellow", "bold"))
    end()


def show_metrics(res: Dict[str, Any]) -> None:
    m = res["metrics"]
    parts = [f"LLM {m['llm_calls']}", f"tool {m['tool_calls']}", f"{m['tokens_in'] + m['tokens_out']:,} token",
             f"${m['cost_usd']:.5f}", f"{m['elapsed_sec']}s"]
    print(c("  📊 " + "  ·  ".join(parts), "gray"))
    print(rule())


def show_result(res: Dict[str, Any], turn: int = 0, trace: bool = True) -> None:
    steps = res.get("steps_log", [])
    print()
    head = f" LƯỢT {turn} " if turn else " KẾT QUẢ "
    meta = f" mẫu {res['agent_type']} · {res['user_id']} "
    print(c("━━" + head, "bold", "cyan") + c("━" * max(2, W - 4 - len(head) - len(meta)), "cyan")
          + c(meta, "cyan") + c("━━", "cyan"))
    show_request(steps, res)
    if trace:
        show_trace(steps)
    show_answer(res)
    show_checks(res)
    if res.get("handoff"):
        show_handoff(res["handoff"])
    show_metrics(res)


# ------------------------------------------------------------------ người duyệt
def ask_approval(req: Dict[str, Any]) -> str:
    print()
    section("🙋 HARNESS CẦN NGƯỜI DUYỆT", "yellow")
    kv("Định làm gì", req.get("dinh_lam_gi"))
    kv("Vì sao hỏi", req.get("vi_sao_hoi"))
    st = req.get("dang_o_dau") or {}
    kv("Đang ở đâu", ", ".join(f"{k}={v}" for k, v in st.items() if v not in (None, "", [])))
    end()
    return input(c("   Đồng ý? (c/k, Enter = để sau): ", "yellow", "bold")).strip().lower()


def ask_plan_approval(req: Dict[str, Any]) -> str:
    print()
    section("📋 KẾ HOẠCH CẦN DUYỆT", "magenta")
    for s in req["plan"]:
        line(f"{s.get('step_id')}. {c(s.get('tool'), 'bold')}({fmt_args(s.get('args') or {k: v for k, v in s.items() if k not in ('step_id', 'tool', 'objective')})})")
        if s.get("objective"):
            line(c(s["objective"], "gray"), 3)
    end()
    return input(c("   Duyệt kế hoạch? (c/k, Enter = có): ", "magenta", "bold")).strip().lower()


# ------------------------------------------------------------------ CSDL & trợ giúp
def show_db(flights: List[Dict[str, Any]], bookings: Dict[str, Dict[str, Any]]) -> None:
    print()
    section("CHUYẾN BAY")
    line(c(f"{'Mã':<7} {'Chặng':<10} {'Ngày':<11} {'Giờ':<6} {'Giá':>12}  Ghế", "bold"))
    for f in flights:
        seat = c("HẾT CHỖ", "red") if not f["seats_available"] else f"còn {f['seats_available']}"
        line(f"{f['flight_id']:<7} {f['origin'] + '→' + f['destination']:<10} {f['date']:<11} "
             f"{f['departure_time']:<6} {money(f['price']):>12}  {seat}")
    end()
    section("VÉ ĐÃ ĐẶT")
    if not bookings:
        line(c("(chưa có vé)", "gray"))
    for code, b in bookings.items():
        st = c(b["status"], "green" if b["status"] == "CONFIRMED" else "red")
        line(f"{code:<9} {b['flight_id']:<7} {b['passenger_name']:<20} {st}  " + c(f"user={b['user_id']}", "gray"))
    end()


HELP = [
    ("/help", "xem hướng dẫn"),
    ("/status", "xem chuyến bay và vé trong CSDL"),
    ("/reset", "làm mới phiên và CSDL"),
    ("/mau <tên>", "đổi mẫu agent: ReAct | Plan-then-Execute | Lai (phiên mới)"),
    ("/user <id>", "đổi tài khoản (giữ phiên)"),
    ("/duyet <chế độ>", "hoi | tu-dong | tu-choi (phiên mới)"),
    ("/trace", "bật / tắt in diễn biến"),
    ("exit", "thoát"),
]


def show_help() -> None:
    section("LỆNH")
    for cmd, desc in HELP:
        line(c(f"{cmd:<16}", "bold") + desc)
    end()


def info(msg: str) -> None:
    print(c(f"  {msg}", "cyan"))


def warn(msg: str) -> None:
    print(c(f"  ⚠ {msg}", "yellow"))


def error(msg: str) -> None:
    print(c(f"  ✗ {msg}", "red", "bold"))
