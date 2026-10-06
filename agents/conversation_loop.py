# -*- coding: utf-8 -*-
"""Hội thoại đa lượt trên console, có NGƯỜI DUYỆT thật cho hành động vượt thẩm quyền.

Phần hiển thị nằm ở agents/console_ui.py; file này chỉ lo vòng lặp hội thoại và lệnh.
Lệnh: /help /status /reset /mau <ReAct|Plan-then-Execute|Lai> /user <id> /duyet <tu-dong|hoi|tu-choi> /trace exit
"""
from typing import Any, Dict, Optional

from agents import AGENT_CLASSES, create_agent
from agents import console_ui as ui
from tools.mock_database import USERS, db

YES = ("c", "co", "có", "y", "yes")


# ---------------------------------------------------------------- người duyệt
def console_approver(req: Dict[str, Any]) -> Optional[bool]:
    ans = ui.ask_approval(req)
    if not ans:
        return None
    return ans in YES


def console_plan_approver(req: Dict[str, Any]) -> Optional[bool]:
    ans = ui.ask_plan_approval(req)
    return ans in YES or ans == ""


APPROVER_MODES = {
    "hoi": (console_approver, console_plan_approver),
    "tu-dong": (lambda r: True, None),
    "tu-choi": (lambda r: False, None),
}


# ---------------------------------------------------------------- in kết quả (giữ tên cũ cho main.py)
def print_result(res: Dict[str, Any], trace: bool = True, turn: int = 0):
    ui.show_result(res, turn=turn, trace=trace)


def print_db_status():
    ui.show_db(db.flights, db.bookings)


# ---------------------------------------------------------------- phiên chat
class ConversationalSession:
    def __init__(self, agent_type: str = "Lai", user_id: str = "user_customer_1", approval_mode: str = "hoi"):
        self.agent_type, self.user_id, self.approval_mode = agent_type, user_id, approval_mode
        self.agent = self._create()

    def _create(self):
        approver, plan_approver = APPROVER_MODES[self.approval_mode]
        return create_agent(self.agent_type, user_id=self.user_id, approver=approver, plan_approver=plan_approver)

    @property
    def turn(self) -> int:
        return len(self.agent.turns_history)

    def send(self, text: str) -> Dict[str, Any]:
        return self.agent.chat(text)


def _banner(s: ConversationalSession):
    user = USERS.get(s.user_id, {})
    ui.banner("✈  AGENT ĐẶT VÉ MÁY BAY · SE373",
              f"mẫu {s.agent_type}  ·  tài khoản {s.user_id} ({user.get('role', '?')})  ·  duyệt: {s.approval_mode}"
              "  ·  gõ /help để xem lệnh")


def start_interactive_chat(agent_type: str = "Lai", user_id: str = "user_customer_1", approval_mode: str = "hoi"):
    s = ConversationalSession(agent_type, user_id, approval_mode)
    show_trace = True
    _banner(s)
    while True:
        try:
            text = input("\n" + ui.c(f"👤 [{s.user_id} · {s.agent_type}] › ", "bold")).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if not text:
            continue
        if text.lower() in ("exit", "quit"):
            break
        if text.startswith("/"):
            parts = text.split()
            cmd, arg = parts[0].lower(), (parts[1] if len(parts) > 1 else None)
            if cmd == "/help":
                ui.show_help()
            elif cmd == "/status":
                print_db_status()
            elif cmd == "/reset":
                db.reset()
                s.agent = s._create()
                ui.info("🔄 Đã làm mới phiên và CSDL.")
            elif cmd == "/mau" and arg in AGENT_CLASSES:
                s.agent_type = arg
                s.agent = s._create()
                ui.info(f"⚙  Mẫu: {arg} (phiên mới)")
            elif cmd == "/user" and arg in USERS:
                s.user_id = arg
                s.agent.set_user(arg)
                ui.info(f"🔑 Tài khoản: {arg} ({USERS[arg]['role']})")
            elif cmd == "/duyet" and arg in APPROVER_MODES:
                s.approval_mode = arg
                s.agent = s._create()
                ui.info(f"🙋 Chế độ duyệt: {arg} (phiên mới)")
            elif cmd == "/trace":
                show_trace = not show_trace
                ui.info(f"Diễn biến: {'bật' if show_trace else 'tắt'}")
            else:
                ui.warn("Lệnh không hợp lệ. Gõ /help.")
            continue
        try:
            res = s.send(text)
            print_result(res, trace=show_trace, turn=s.turn)
        except Exception as e:  # lỗi mạng / API: báo rõ, không crash phiên
            ui.error(f"{type(e).__name__}: {e}")
    ui.info("Tạm biệt!")
