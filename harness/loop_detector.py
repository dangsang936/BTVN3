# -*- coding: utf-8 -*-
"""SE373 · Phát hiện lặp và bế tắc.

  1. Trùng action      : cùng (tool, args) xuất hiện lại trong cửa sổ `window` lượt.
                         Ngoại lệ: tool polling (check_booking_status) được gọi lại tối đa
                         `poll_limit` lần, vì "gọi lại get_booking để chờ confirmed là polling hợp lệ".
  2. Trùng observation : tham số khác nhau nhưng kết quả giống hệt nhau `same_obs_k` lần.
  3. Không tiến triển  : đại lượng tiến triển của BÀI TOÁN (do harness tính từ ràng buộc,
                         không phải số bước) đứng yên `stall_n` lượt liên tiếp.

Detector được reset ở đầu mỗi lượt hội thoại (start_turn) để lượt sau không bị chặn oan
vì một lời gọi hợp lệ ở lượt trước.
"""
from collections import deque
from typing import Any, Dict, Optional

POLLING_TOOLS = {"check_booking_status"}


class FlightLoopDetector:
    def __init__(self, window: int = 6, repeat_k: int = 2, same_obs_k: int = 3,
                 stall_n: int = 4, poll_limit: int = 3):
        self.window, self.repeat_k, self.same_obs_k = window, repeat_k, same_obs_k
        self.stall_n, self.poll_limit = stall_n, poll_limit
        self.reset()

    def reset(self):
        self.recent_actions = deque(maxlen=self.window)
        self.recent_obs = deque(maxlen=self.window)
        self.last_progress: Optional[Any] = None
        self.stall_count = 0

    @staticmethod
    def fingerprint(tool_name: str, args: Dict[str, Any]):
        return tool_name, repr(sorted((k, str(v).strip().upper()) for k, v in args.items() if k != "user_id"))

    def check_action(self, tool_name: str, args: Dict[str, Any]) -> Optional[str]:
        fp = self.fingerprint(tool_name, args)
        limit = self.poll_limit if tool_name in POLLING_TOOLS else self.repeat_k
        count = self.recent_actions.count(fp) + 1
        if count >= limit:
            return (f"LOOP_ACTION · {tool_name}{dict(args)} lặp lại {count} lần "
                    f"trong {self.window} lượt gần nhất.")
        self.recent_actions.append(fp)
        return None

    def check_observation(self, observation: Any) -> Optional[str]:
        fp = repr(observation)
        count = self.recent_obs.count(fp) + 1
        self.recent_obs.append(fp)
        if count >= self.same_obs_k:
            return f"LOOP_OBSERVATION · {count} lời gọi nhận về cùng một kết quả."
        return None

    def check_progress(self, progress: Any) -> Optional[str]:
        if progress == self.last_progress:
            self.stall_count += 1
        else:
            self.stall_count = 0
            self.last_progress = progress
        if self.stall_count >= self.stall_n:
            return (f"STALL · Đại lượng tiến triển đứng yên ở {progress} "
                    f"qua {self.stall_count} lượt liên tiếp.")
        return None
