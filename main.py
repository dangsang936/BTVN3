# -*- coding: utf-8 -*-
"""SE373 · BTVN #3 · Agent đặt vé máy bay với harness.

Cách chạy:
  python main.py                                   # chat đa lượt, mẫu Lai, hỏi người duyệt trên console
  python main.py --mau ReAct --user guest_01       # đổi mẫu / tài khoản
  python main.py --query "Đặt vé HAN đi SGN ngày 2026-10-15 ..."   # chạy một lượt
  python main.py --danh-gia --lan 3                # ma trận đánh giá 3 mẫu (cần API key)
"""
import argparse

from agents import AGENT_CLASSES
from agents.conversation_loop import APPROVER_MODES, ConversationalSession, print_result, start_interactive_chat
from tools.mock_database import USERS


def main():
    p = argparse.ArgumentParser(description="Agent đặt vé máy bay SE373")
    p.add_argument("--mau", choices=list(AGENT_CLASSES), default="Lai")
    p.add_argument("--user", choices=list(USERS), default="user_customer_1")
    p.add_argument("--duyet", choices=list(APPROVER_MODES), default="hoi",
                   help="Cách xử lý yêu cầu cần người duyệt: hoi (console) | tu-dong | tu-choi")
    p.add_argument("--query", type=str, default=None)
    p.add_argument("--danh-gia", dest="danh_gia", action="store_true")
    p.add_argument("--lan", type=int, default=3, help="Số lần chạy lặp mỗi ô khi đánh giá")
    a = p.parse_args()

    if a.danh_gia:
        from evaluation import main as eval_main
        eval_main(runs=a.lan)
    elif a.query:
        print_result(ConversationalSession(a.mau, a.user, a.duyet).send(a.query))
    else:
        start_interactive_chat(a.mau, a.user, a.duyet)


if __name__ == "__main__":
    main()
