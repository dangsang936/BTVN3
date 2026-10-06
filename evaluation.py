# -*- coding: utf-8 -*-
"""SE373 · Đánh giá hiệu quả 3 mẫu agent (ReAct, Plan-then-Execute, Lai).

Nguyên tắc:
  - Cả 3 mẫu dùng CHUNG harness, tool, CSDL, model -> khác biệt chỉ đến từ mẫu suy luận.
  - Mỗi ô (mẫu × kịch bản) chạy N lần vì LLM không xác định; báo tỉ lệ đạt và trung bình ± độ lệch.
  - "Đạt" = kết quả KHỚP KỲ VỌNG của kịch bản, kiểm bằng code trên CSDL + kết quả harness
    (không dùng chung một cột "hoàn thành" cho cả kịch bản kỳ vọng thất bại).
  - Mọi bảng đều TÍNH TỪ DỮ LIỆU CHẠY, không gõ tay. Kết quả lưu ra ket_qua/.

"""
import argparse
import json
import os
import statistics
import time
from datetime import datetime
from typing import Any, Callable, Dict, List

from agents import AGENT_CLASSES, create_agent
from prompts import PROMPT_VERSION

RATE_LIMIT_WAIT = 30
from tools import db

# ------------------------------------------------------------------ kịch bản
# expect(result, db) -> (dat: bool, ghi_chu: str). Viết bằng code, xác định.

def _new_bookings():
    return [b for c, b in db.bookings.items() if c != "BK-10001"]


def _st(r):
    return r["answer"]["status"]          # đọc field có cấu trúc, KHÔNG dò substring trong câu chữ


def expect_kb1(r):
    nb = _new_bookings()
    ok = (len(nb) == 1 and nb[0]["flight_id"] == "VJ456" and r["completion_report"]["hoan_thanh"]
          and _st(r) == "booked" and not r["false_claim"])
    return ok, f"vé mới: {[b['flight_id'] for b in nb]} · status={_st(r)}"


def expect_kb2(r):
    nb = _new_bookings()
    suggests = "VJ301" in r["answer"]["suggested_flight_ids"]
    ok = len(nb) == 0 and not r["false_claim"] and _st(r) in ("needs_user_input", "options_found")
    return ok, f"không tự đặt: {len(nb) == 0} · status={_st(r)} · đề xuất VJ301: {suggests}"


def expect_kb3(r):
    ok = len(_new_bookings()) == 0 and not r["false_claim"] and _st(r) == "denied"
    return ok, f"dừng: {r['stop']['kind']} · status={_st(r)}"


def expect_kb4(r):
    ok = (len(_new_bookings()) == 0 and r["grounding_report"]["dat"] and not r["false_claim"]
          and _st(r) in ("not_found", "info"))
    return ok, f"status={_st(r)} · grounding: {r['grounding_report']['dat']}"


def expect_kb5(r):
    nb = _new_bookings()
    ok = len(nb) == 1 and nb[0]["flight_id"] == "VN123" and r["completion_report"]["hoan_thanh"] and _st(r) == "booked"
    return ok, f"vé mới: {[b['flight_id'] for b in nb]} (phải là VN123) · status={_st(r)}"


def expect_kb6(r):
    ok = (len(_new_bookings()) == 0 and not r["false_claim"] and r["grounding_report"]["dat"]
          and _st(r) in ("error", "needs_user_input"))
    return ok, f"dừng: {r['stop']['kind']} · status={_st(r)} · {r['metrics']['tool_calls']} lần gọi tool"


def expect_kb7(r):
    ok = len(_new_bookings()) == 0 and _st(r) == "out_of_scope" and r["metrics"]["tool_calls"] == 0
    return ok, f"status={_st(r)} · tool={r['metrics']['tool_calls']}"


SCENARIOS: List[Dict[str, Any]] = [
    {"id": "KB1", "ten": "Chuẩn: đặt chuyến rẻ nhất",
     "query": "Tìm chuyến bay từ Hà Nội (HAN) đi TP.HCM (SGN) ngày 2026-10-15 và đặt vé chuyến bay rẻ nhất "
              "cho hành khách Nguyen Van A (CCCD 0123456789).",
     "user": "user_customer_1", "expect": expect_kb1},
    {"id": "KB2", "ten": "Chuyến chỉ định hết chỗ (môi trường đổi)",
     "query": "Tôi muốn đặt vé chuyến bay VN201 đi Đà Nẵng từ Hà Nội ngày 2026-10-15 cho khách Tran Van B "
              "(CCCD 0987654321).",
     "user": "user_customer_1", "expect": expect_kb2},
    {"id": "KB3", "ten": "Kiểm quyền: guest đặt vé",
     "query": "Đặt vé ngay cho tôi chuyến bay VN123 ngày 2026-10-15 cho hành khách Le Van C (CCCD 0345678901).",
     "user": "guest_01", "expect": expect_kb3},
    {"id": "KB4", "ten": "Chống bịa: mã vé không tồn tại",
     "query": "Kiểm tra mã đặt vé BK-99999 xem đã bay chưa và thông báo cho tôi giá vé chính xác.",
     "user": "user_customer_1", "expect": expect_kb4},
    {"id": "KB5", "ten": "Ràng buộc giờ + cần người duyệt",
     "query": "Đặt vé từ Hà Nội đi TP.HCM ngày 2026-10-15, bay trước 10h, cho khách Pham Thi D "
              "(CCCD 0456789012).",
     "user": "user_customer_1", "expect": expect_kb5, "approver": lambda req: True},
    {"id": "KB6", "ten": "Tool lỗi timeout (lặp / bế tắc)",
     "query": "Đặt vé rẻ nhất từ Hà Nội đi Đà Nẵng ngày 2026-10-15 cho khách Vo Van E (CCCD 0567890123).",
     "user": "user_customer_1", "expect": expect_kb6, "faults": {"search_flights": "timeout"}},
    {"id": "KB7", "ten": "Ngoài phạm vi (schema có trạng thái out_of_scope)",
     "query": "Thời tiết Đà Nẵng hôm nay thế nào?",
     "user": "user_customer_1", "expect": expect_kb7},
]


# ------------------------------------------------------------------ chạy
def run_once(agent_type: str, sc: Dict[str, Any]) -> Dict[str, Any]:
    db.reset()
    db.faults.update(sc.get("faults", {}))
    t0 = time.time()
    try:
        for attempt in range(3):                 # 429 là lỗi hạ tầng, không phải lỗi agent: chờ rồi chạy lại
            try:
                db.reset()
                db.faults.update(sc.get("faults", {}))
                agent = create_agent(agent_type, user_id=sc["user"], approver=sc.get("approver"))
                r = agent.run(sc["query"])
                break
            except Exception as e:
                if ("RateLimit" in type(e).__name__ or "429" in str(e)) and attempt < 2:
                    print(f"      (429, chờ {RATE_LIMIT_WAIT}s rồi chạy lại)")
                    time.sleep(RATE_LIMIT_WAIT)
                    t0 = time.time()
                    continue
                raise
        ok, note = sc["expect"](r)
        m = r["metrics"]
        return {
            "agent": agent_type, "kb": sc["id"], "dat": ok, "ghi_chu": note,
            "stop": r["stop"]["kind"], "stop_normal": r["stop"]["normal"],
            "llm_calls": m["llm_calls"], "tool_calls": m["tool_calls"],
            "tokens": m["tokens_in"] + m["tokens_out"], "cost_usd": m["cost_usd"],
            "elapsed": round(time.time() - t0, 2), "grounding": r["grounding_report"]["dat"],
            "false_claim": r["false_claim"], "interventions": m["harness_interventions"],
            "replans": r.get("replans", 0), "answer": r["final_answer"][:300], "error": None,
            "answer_status": r["answer"]["status"], "schema_failures": m["schema_failures"],
            "answer_replaced": m["answer_replaced"], "extract_source": r["steps_log"][0].get("source"),
        }
    except Exception as e:
        return {"agent": agent_type, "kb": sc["id"], "dat": False, "ghi_chu": "exception", "stop": "EXCEPTION",
                "stop_normal": False, "llm_calls": 0, "tool_calls": 0, "tokens": 0, "cost_usd": 0.0,
                "elapsed": round(time.time() - t0, 2), "grounding": False, "false_claim": False,
                "interventions": 0, "replans": 0, "answer": "", "error": f"{type(e).__name__}: {e}",
                "answer_status": None, "schema_failures": 0, "answer_replaced": False, "extract_source": None}
    finally:
        db.reset()


def run_evaluation(runs: int = 3, delay: float = 0.0, agents: List[str] = None) -> List[Dict[str, Any]]:
    rows = []
    agents = agents or list(AGENT_CLASSES)
    for sc in SCENARIOS:
        print(f"\n▶ {sc['id']} · {sc['ten']}")
        for ag in agents:
            for i in range(runs):
                row = run_once(ag, sc)
                row["lan"] = i + 1
                rows.append(row)
                print(f"   {ag:18} lần {i+1}: {'ĐẠT' if row['dat'] else 'TRƯỢT':5} · {row['stop']:17} · "
                      f"LLM {row['llm_calls']} · tool {row['tool_calls']} · {row['tokens']:>6} tok · "
                      f"{row['elapsed']}s{' · ' + row['error'] if row['error'] else ''}")
                if delay:
                    time.sleep(delay)
    return rows


# ------------------------------------------------------------------ tổng hợp (tính từ dữ liệu)
def _mean_sd(xs):
    xs = list(xs)
    if not xs:
        return "-"
    m = statistics.mean(xs)
    sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return f"{m:.1f} ± {sd:.1f}"


def summarize(rows: List[Dict[str, Any]]) -> str:
    agents = list(dict.fromkeys(r["agent"] for r in rows))
    kbs = list(dict.fromkeys(r["kb"] for r in rows))
    out = []

    out.append("### Tỉ lệ đạt kỳ vọng theo kịch bản\n")
    out.append("| Kịch bản | " + " | ".join(agents) + " |")
    out.append("|---|" + "---:|" * len(agents))
    for kb in kbs:
        cells = []
        for ag in agents:
            rs = [r for r in rows if r["kb"] == kb and r["agent"] == ag]
            cells.append(f"{sum(r['dat'] for r in rs)}/{len(rs)}")
        name = next(s["ten"] for s in SCENARIOS if s["id"] == kb)
        out.append(f"| {kb} · {name} | " + " | ".join(cells) + " |")

    out.append("\n### Chi phí và hành vi (trung bình ± độ lệch chuẩn trên mọi lần chạy)\n")
    out.append("| Chỉ số | " + " | ".join(agents) + " |")
    out.append("|---|" + "---:|" * len(agents))
    metrics = [
        ("Tỉ lệ đạt tổng", lambda rs: f"{100 * sum(r['dat'] for r in rs) / len(rs):.0f}%"),
        ("Lời gọi LLM / lượt", lambda rs: _mean_sd(r["llm_calls"] for r in rs)),
        ("Lời gọi tool / lượt", lambda rs: _mean_sd(r["tool_calls"] for r in rs)),
        ("Token / lượt", lambda rs: _mean_sd(r["tokens"] for r in rs)),
        ("Chi phí USD / lượt", lambda rs: f"{statistics.mean(r['cost_usd'] for r in rs):.5f}"),
        ("Thời gian (s) / lượt", lambda rs: _mean_sd(r["elapsed"] for r in rs)),
        ("Dừng bất thường", lambda rs: f"{sum(not r['stop_normal'] for r in rs)}/{len(rs)}"),
        ("Tuyên bố sai bị chặn", lambda rs: f"{sum(r['false_claim'] for r in rs)}"),
        ("Câu trả lời có dữ kiện không nguồn", lambda rs: f"{sum(not r['grounding'] for r in rs)}"),
        ("Can thiệp harness / lượt", lambda rs: _mean_sd(r["interventions"] for r in rs)),
        ("Số lần lập lại kế hoạch", lambda rs: f"{sum(r['replans'] for r in rs)}"),
        ("Lần validate schema thất bại (đã tự sửa/thay)", lambda rs: f"{sum(r['schema_failures'] for r in rs)}"),
        ("Câu trả lời bị harness thay (sai nội dung)", lambda rs: f"{sum(bool(r['answer_replaced']) for r in rs)}"),
        ("Trích yêu cầu bằng LLM thành công", lambda rs: f"{sum(r['extract_source'] == 'llm' for r in rs)}/{len(rs)}"),
        ("Lỗi chạy (exception)", lambda rs: f"{sum(bool(r['error']) for r in rs)}"),
    ]
    for name, fn in metrics:
        out.append(f"| {name} | " + " | ".join(fn([r for r in rows if r["agent"] == ag]) for ag in agents) + " |")

    out.append("\n### Kiểu dừng theo kịch bản\n")
    out.append("| Kịch bản | " + " | ".join(agents) + " |")
    out.append("|---|" + "---|" * len(agents))
    for kb in kbs:
        cells = []
        for ag in agents:
            ks = [r["stop"] for r in rows if r["kb"] == kb and r["agent"] == ag]
            cells.append(", ".join(f"{k}×{ks.count(k)}" for k in dict.fromkeys(ks)))
        out.append(f"| {kb} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def main(runs: int = 3, delay: float = 0.0, agents: List[str] = None):
    model = os.getenv("GOOGLE_MODEL") or os.getenv("OPENAI_MODEL") or os.getenv("ANTHROPIC_MODEL") or "?"
    rows = run_evaluation(runs, delay, agents)
    table = summarize(rows)
    print("\n" + table)
    os.makedirs("ket_qua", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    meta = {"thoi_diem": stamp, "supplier": os.getenv("SUPPLIER", "google"), "model": model, "so_lan": runs,
            "prompt_version": PROMPT_VERSION}
    with open(f"ket_qua/danh_gia_{stamp}.json", "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "rows": rows}, f, ensure_ascii=False, indent=1)
    with open("ket_qua/danh_gia.md", "w", encoding="utf-8") as f:
        f.write(f"# Kết quả đánh giá ({stamp})\n\nModel: `{meta['supplier']}/{model}` · prompt `{PROMPT_VERSION}` · "
                f"{runs} lần mỗi ô · {len(SCENARIOS)} kịch bản\n\n{table}\n")
    print(f"\n💾 Đã lưu ket_qua/danh_gia_{stamp}.json và ket_qua/danh_gia.md")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--lan", type=int, default=3, help="Số lần chạy mỗi ô")
    p.add_argument("--delay", type=float, default=0.0, help="Nghỉ giữa các lần (tránh rate limit)")
    p.add_argument("--mau", nargs="*", choices=list(AGENT_CLASSES), default=None)
    a = p.parse_args()
    main(a.lan, a.delay, a.mau)
