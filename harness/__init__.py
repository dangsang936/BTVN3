# -*- coding: utf-8 -*-
"""Các lớp harness của agent đặt vé (SE373 · Buổi 03).

  constraints.py        Ràng buộc là dữ liệu
  completion_checker.py Tiêu chí hoàn thành kiểm bằng code
  permission_checker.py Kiểm quyền (allow / deny / chờ người duyệt)
  handoff.py            Bàn giao cho con người
  loop_detector.py      Phát hiện lặp + bế tắc
  budget.py             Ngân sách: bước, token, thời gian, chi phí
  grounding.py          Đối chiếu câu trả lời với dữ liệu tool (chống bịa)
  output_validator.py   Kiểm nội dung output đã đúng schema (yêu cầu, kế hoạch, câu trả lời)
  tool_arg_validator.py Kiểm Ý NGHĨA tham số tool trước khi thực thi (đúng kiểu ≠ đúng ý nghĩa)
  harness_manager.py    Điều phối tất cả theo checklist của slide
"""
from harness.budget import BudgetLimits, BudgetTracker
from harness.completion_checker import FlightCompletionChecker
from harness.constraints import Constraints
from harness.grounding import chan_truoc_khi_tra_loi, kiem_can_cu_dat_ve, phat_hien_tuyen_bo_dat_ve
from harness.handoff import dinh_dang_ban_giao, tao_ban_giao
from harness.harness_manager import (ANSWERED, BUDGET, DENIED, GOAL, HUMAN, LOOP, NORMAL_STOPS, STALL,
                                     Decision, FlightHarnessManager)
from harness.loop_detector import FlightLoopDetector
from harness.permission_checker import FlightPermissionChecker, PermissionDecision
