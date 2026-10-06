# -*- coding: utf-8 -*-
"""SE373 · Bộ điều phối harness.

    01 Dựng ngữ cảnh      -> start_turn() + constraints_prompt()
    02 Model đề xuất tool -> (agent gọi model)
    03 Harness gọi tool   -> run_tool(): tên tool -> quyền -> đúng kiểu (args_schema) -> đúng ý nghĩa
                             (tool_arg_validator) -> ràng buộc -> người duyệt -> thực thi
    04 Ghi kết quả        -> run_tool() lưu observation, vé đã tạo, ứng viên tốt nhất
    05 Xét điều kiện dừng -> run_tool() trả về Decision theo đúng thứ tự checklist của slide:

    #  CHẠY KHI NÀO              KIỂM GÌ                                  KẾT THÚC KIỂU
    0  trước khi thực thi tool    quyền hạn (+ ràng buộc trước book)      NEEDS_HUMAN / DENIED
    1  sau observation            tiêu chí hoàn thành (code đọc CSDL)     GOAL_REACHED
    2  sau observation            (tool, args) trùng / observation trùng  LOOP
    3  sau observation            đại lượng tiến triển đứng yên           STALL
    4  sau observation            vòng · token · thời gian · tiền          BUDGET

Ba agent (ReAct, Plan-then-Execute, Lai) dùng CHUNG lớp này, nên khác biệt khi đánh giá
chỉ đến từ mẫu suy luận, không đến từ harness.
"""
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from harness.budget import BudgetLimits, BudgetTracker
from harness.completion_checker import FlightCompletionChecker
from harness.constraints import Constraints
from harness.grounding import chan_truoc_khi_tra_loi, kiem_can_cu_dat_ve, phat_hien_tuyen_bo_dat_ve
from harness.handoff import tao_ban_giao
from harness.loop_detector import FlightLoopDetector
from harness.output_validator import validate_answer
from harness.permission_checker import ALLOW, APPROVE, DENY, FlightPermissionChecker
from harness.tool_arg_validator import check_tool_semantics
from llm_io import validation_errors
from pydantic import BaseModel, ValidationError
from schemas import FinalAnswer, ToolResult

# Kiểu dừng (slide "5 điều kiện dừng") + phân loại bình thường / bất thường
GOAL = "GOAL_REACHED"          # bình thường
ANSWERED = "MODEL_ANSWERED"    # bình thường: model thôi gọi tool (cần kiểm chứng trước khi tin)
HUMAN = "NEEDS_HUMAN"          # bình thường: chờ người duyệt / thiếu thông tin
DENIED = "PERMISSION_DENIED"   # bất thường
LOOP = "LOOP"                  # bất thường
STALL = "STALL"                # bất thường
BUDGET = "BUDGET"              # bất thường
NORMAL_STOPS = {GOAL, ANSWERED, HUMAN}

# Hàm duyệt: nhận gói yêu cầu, trả True (đồng ý) / False (từ chối) / None (chưa có ai trả lời)
Approver = Callable[[Dict[str, Any]], Optional[bool]]


@dataclass
class Decision:
    stop: bool = False
    kind: Optional[str] = None
    reason: Optional[str] = None
    handoff: Optional[Dict[str, Any]] = None


class FlightHarnessManager:
    def __init__(self, user_id: str = "user_customer_1", approver: Optional[Approver] = None,
                 limits: Optional[BudgetLimits] = None):
        self.user_id = user_id
        self.approver = approver
        self.permission = FlightPermissionChecker(user_id)
        self.loop = FlightLoopDetector(window=6, repeat_k=2, same_obs_k=3, stall_n=4, poll_limit=3)
        self.completion = FlightCompletionChecker()
        self.budget = BudgetTracker(limits or BudgetLimits())
        self.constraints = Constraints()
        self.reset_session()

    # ------------------------------------------------------------------ vòng đời
    def reset_session(self):
        self.constraints = Constraints()
        self.observations: List[str] = []
        self.user_texts: List[str] = []
        self.actions: List[str] = []           # vết "đã thử"
        self.side_effects: List[str] = []      # hành động đã đổi CSDL
        self.session_bookings: List[str] = []
        self.seen_flights: Dict[str, Dict[str, Any]] = {}
        self.interventions: List[Dict[str, Any]] = []
        self.goal_reached = False

    def set_user(self, user_id: str):
        self.user_id = user_id
        self.permission.set_user(user_id)

    def start_turn(self, user_text: str, extracted: Optional[Constraints] = None,
                   reset_budget: bool = True) -> Constraints:
        """Bước 01: ghi yêu cầu thành dữ liệu, reset detector + ngân sách cho lượt mới.
        `extracted`: ràng buộc do model trích (structured output, đã validate + kiểm căn cứ);
        không có thì dùng bộ trích regex xác định."""
        self.user_texts.append(user_text)
        new = extracted if extracted is not None else Constraints.from_text(user_text)
        self.constraints = self.constraints.merge(new) if self.constraints.intent != "unknown" else new
        self.loop.reset()
        if reset_budget:
            self.budget.start_turn()
        self.goal_reached = False
        self.interventions = []
        return self.constraints

    def constraints_json(self) -> str:
        """Ràng buộc dưới dạng DỮ LIỆU để đưa vào prompt (trong thẻ XML, không trộn với instruction)."""
        d = self.constraints.to_dict()
        if self.constraints.intent == "book" and self.constraints.missing_for_booking():
            d["con_thieu"] = self.constraints.missing_for_booking()
        return json.dumps(d, ensure_ascii=False)

    def constraints_prompt(self) -> str:
        c = self.constraints
        lines = [
            "[RÀNG BUỘC DO HARNESS QUẢN LÝ - không được tự ý thay đổi]",
            json.dumps(c.to_dict(), ensure_ascii=False),
            "Mọi lệnh book_flight vi phạm ràng buộc sẽ bị harness chặn (status=denied).",
        ]
        if c.intent == "book" and c.missing_for_booking():
            lines.append("Còn thiếu: " + ", ".join(c.missing_for_booking()) + " -> hãy hỏi người dùng, KHÔNG được bịa.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ tiện ích
    def _state(self) -> Dict[str, Any]:
        best = self.best_candidate()
        return {
            "user_id": self.user_id,
            "intent": self.constraints.intent,
            "chuyen_tot_nhat_da_thay": best["flight_id"] if best else None,
            "ve_da_tao": list(self.session_bookings),
            "tien_trien": self.progress(),
        }

    def handoff(self, kind: str, reason: str, question: str) -> Dict[str, Any]:
        h = tao_ban_giao(ly_do=reason, da_thu=self.actions, trang_thai=self._state(), cau_hoi=question,
                         loai_dung=kind, tac_dung_phu=self.side_effects, rang_buoc=self.constraints.to_dict())
        self.interventions.append({"kind": kind, "reason": reason})
        return h

    def _stop(self, kind: str, reason: str, question: str) -> Decision:
        return Decision(True, kind, reason, self.handoff(kind, reason, question))

    def best_candidate(self) -> Optional[Dict[str, Any]]:
        return self.constraints.best_candidate(list(self.seen_flights.values()))

    def progress(self) -> Tuple[int, int]:
        """Đại lượng tiến triển của bài toán: (giai đoạn, số ràng buộc chuyến tốt nhất đã thỏa).
        giai đoạn 0 = chưa thấy chuyến hợp lệ, 1 = đã có ứng viên thỏa hết, 2 = đã có vé."""
        flights = list(self.seen_flights.values())
        best_score = max((self.constraints.score(f) for f in flights), default=0)
        stage = 2 if self.session_bookings else (1 if self.best_candidate() else 0)
        return stage, best_score

    def _normalize_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        args = dict(args or {})
        if tool_name in ("book_flight", "cancel_flight_booking"):
            args["user_id"] = self.user_id          # KHÔNG tin user_id do model sinh
        if tool_name == "book_flight":
            if args.get("flight_id"):
                args["flight_id"] = str(args["flight_id"]).upper().strip()
            # Model không truyền thông tin hành khách thì lấy từ ràng buộc (do người dùng cung cấp);
            # ràng buộc cũng không có thì để trống -> validate tham số sẽ chặn, không cho bịa.
            for k in ("passenger_name", "passenger_id"):
                if not args.get(k) and getattr(self.constraints, k):
                    args[k] = getattr(self.constraints, k)
        return args

    def _record_observation(self, tool_name: str, args: Dict[str, Any], obs: str):
        self.observations.append(obs)
        try:
            data = json.loads(obs)
        except Exception:
            return
        if tool_name == "search_flights":
            for f in data.get("flights") or []:
                self.seen_flights[f["flight_id"]] = f
        elif tool_name == "get_flight_details" and data.get("status") == "ok":
            self.seen_flights[data["flight"]["flight_id"]] = data["flight"]
        elif tool_name == "book_flight" and data.get("status") == "ok":
            b = data["booking"]
            self.session_bookings.append(b["booking_code"])
            self.side_effects.append(f"Đã tạo vé {b['booking_code']} ({b['flight_id']})")
        elif tool_name == "cancel_flight_booking" and data.get("status") == "ok":
            self.side_effects.append(f"Đã hủy vé {args.get('booking_code')}")

    def record_llm(self, ai_msg: Any):
        self.budget.record_llm(ai_msg)

    def check_budget(self) -> Decision:
        over = self.budget.exceeded()
        if over:
            return self._stop(BUDGET, over, "Agent đã hết ngân sách. Có tiếp tục với ngân sách mới không?")
        return Decision()

    def _reject_args(self, tool_name: str, args: Dict[str, Any], action: str, param: str, message: str,
                     hint: str, kind: str = "ARGS_INVALID") -> Tuple[str, Decision]:
        """Application KHÔNG thực thi tool call; trả observation invalid_param (gắn với đúng tool call)
        để model tự sửa. Lặp lại cùng lời gọi sai -> bộ phát hiện lặp / bế tắc dừng vòng lặp."""
        obs = ToolResult(status="invalid_param", param=param, message=message[:400],
                         hint=hint).model_dump_json(exclude_none=True)
        self.observations.append(obs)
        self.actions.append(f"{action} -> invalid_param: {message[:200]}")
        self.interventions.append({"kind": kind, "reason": message[:300]})
        loop_msg = self.loop.check_action(tool_name, args)
        if loop_msg:
            return obs, self._stop(LOOP, loop_msg, "Agent lặp lại lời gọi sai tham số. Cần người kiểm tra.")
        stall = self.loop.check_progress(self.progress())
        if stall:
            return obs, self._stop(STALL, stall, self._stall_question())
        return obs, self.check_budget()

    # ------------------------------------------------------------------ 03-05: chạy tool
    def run_tool(self, tool_name: str, args: Dict[str, Any], tools_map: Dict[str, Any]) -> Tuple[str, Decision]:
        args = self._normalize_args(tool_name, args)
        action = f"{tool_name}({ {k: v for k, v in args.items() if k != 'user_id'} })"

        # --- 0-1. Tên tool phải nằm trong danh sách tool đã khai báo (model có thể bịa tên tool)
        if tool_name not in tools_map:
            return self._reject_args(tool_name, args, action, "tool", f"Không có tool '{tool_name}'.",
                                     "Chỉ dùng các tool đã được cung cấp: " + ", ".join(sorted(tools_map)) + ".")

        # --- 0-2. Kiểm quyền (TRƯỚC khi thực thi)
        perm = self.permission.check(tool_name, args)
        if perm.verdict == DENY:
            self.actions.append(f"{action} -> bị chặn: {perm.reason}")
            obs = json.dumps({"status": "denied", "reason": perm.reason}, ensure_ascii=False)
            self.observations.append(obs)      # model thấy nội dung này -> phải là nguồn hợp lệ khi kiểm căn cứ
            return (obs,
                    self._stop(DENIED, perm.reason,
                               "Tài khoản không đủ quyền. Đăng nhập tài khoản khác hay chuyển nhân viên xử lý?"))

        # --- 0-3. ĐÚNG KIỂU: validate tham số theo args_schema (Pydantic) TRƯỚC khi gọi hàm
        schema = getattr(tools_map.get(tool_name), "args_schema", None)
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                args = schema.model_validate(args).model_dump(exclude_none=True)
            except ValidationError as e:
                errs = validation_errors(e)
                return self._reject_args(tool_name, args, action,
                                         str(e.errors()[0]["loc"][0]) if e.errors()[0]["loc"] else "args",
                                         "; ".join(errs)[:400],
                                         "Sửa tham số đúng schema. Thiếu thông tin người dùng (họ tên, CCCD) thì "
                                         "hỏi người dùng, không được bịa.")

        # --- 0-4. ĐÚNG Ý NGHĨA: đúng kiểu chưa đủ, đối chiếu với dữ liệu thật (slide "Tool validation")
        issue = check_tool_semantics(tool_name, args)
        if issue:
            return self._reject_args(tool_name, args, action, issue.param, issue.message, issue.hint,
                                     kind="ARGS_MEANINGLESS")

        # --- 0-5. Ràng buộc là dữ liệu: kiểm lại yêu cầu gốc ngay trước book_flight
        if tool_name == "book_flight":
            denied = self._check_booking_constraints(args)
            if denied:
                self.actions.append(f"{action} -> vi phạm ràng buộc: {denied['violations']}")
                self.interventions.append({"kind": "CONSTRAINT_DENIED", "reason": str(denied["violations"])})
                obs = json.dumps(denied, ensure_ascii=False)
                self.observations.append(obs)
                # Không dừng: trả {"status": "denied"} để model tự điều chỉnh; nếu nó cứ thử lại,
                # bộ phát hiện lặp / bế tắc sẽ dừng vòng lặp.
                loop_msg = self.loop.check_action(tool_name, args)
                if loop_msg:
                    return obs, self._stop(LOOP, loop_msg, "Agent lặp lại hành động bị chặn. Cần người quyết định.")
                stall = self.loop.check_progress(self.progress())
                if stall:
                    return obs, self._stop(STALL, stall, self._stall_question())
                return obs, self.check_budget()

        # --- 0-6. Cần người duyệt
        if perm.verdict == APPROVE:
            req = {"dang_o_dau": self._state(), **perm.approval_request, "ly_do": perm.reason}
            answer = self.approver(req) if self.approver else None
            if answer is None:
                self.actions.append(f"{action} -> chờ duyệt")
                obs = json.dumps({"status": "pending_approval", "reason": perm.reason}, ensure_ascii=False)
                self.observations.append(obs)  # vd. ngưỡng 1,500,000 nằm ở đây, không có trong kết quả tool
                return (obs,
                        self._stop(HUMAN, perm.reason,
                                   f"Đồng ý thực hiện: {perm.approval_request.get('dinh_lam_gi')}? (có/không)"))
            if answer is False:
                self.actions.append(f"{action} -> người dùng từ chối")
                obs = json.dumps({"status": "rejected_by_human", "reason": "Người dùng không đồng ý."},
                                 ensure_ascii=False)
                self.observations.append(obs)
                return (obs,
                        self._stop(HUMAN, "Người dùng từ chối phê duyệt.",
                                   "Người dùng không duyệt. Có muốn chọn phương án khác không?"))
            self.interventions.append({"kind": "APPROVED_BY_HUMAN", "reason": perm.reason})

        # --- 2a. Trùng action (kiểm trước khi chạy để không tốn lời gọi tool vô ích)
        loop_msg = self.loop.check_action(tool_name, args)
        if loop_msg:
            self.actions.append(f"{action} -> chặn vì lặp")
            return (json.dumps({"status": "blocked", "reason": loop_msg}, ensure_ascii=False),
                    self._stop(LOOP, loop_msg, "Agent gọi lặp cùng một hành động. Kiểm tra dịch vụ hoặc đổi yêu cầu?"))

        # --- Thực thi tool
        self.budget.record_tool()
        try:                                   # APPLICATION thực thi, không phải model
            obs = tools_map[tool_name].invoke(args)
        except Exception as e:  # tool lỗi -> trạng thái rõ ràng, không crash im lặng
            obs = json.dumps({"status": "error", "error": type(e).__name__, "hint": str(e)[:200]},
                             ensure_ascii=False)
        obs = str(obs)
        try:                                   # observation cũng phải đúng schema ToolResult
            ToolResult.model_validate_json(obs)
        except (ValidationError, ValueError) as e:
            obs = ToolResult(status="error", error="MALFORMED_TOOL_OUTPUT", message=str(e)[:200],
                             hint="Tool trả dữ liệu sai định dạng; không dùng kết quả này.").model_dump_json(exclude_none=True)
        self._record_observation(tool_name, args, obs)
        try:
            st = json.loads(obs).get("status")
        except Exception:
            st = "?"
        self.actions.append(f"{action} -> {st}")

        # --- 1. Tiêu chí hoàn thành
        if tool_name == "book_flight" and st == "ok":
            rep = self.completion_report()
            if rep["hoan_thanh"]:
                self.goal_reached = True
                return obs, Decision(True, GOAL, "Vé đã CONFIRMED trong CSDL và thỏa mọi ràng buộc.")
            # Đặt được nhưng không đạt tiêu chí -> phải báo người (có tác dụng phụ!)
            return obs, self._stop(HUMAN, rep["ly_do"],
                                   f"Vé {self.session_bookings[-1]} đã tạo nhưng không đạt tiêu chí. Giữ hay hủy?")

        # --- 2b. Trùng observation
        obs_msg = self.loop.check_observation(obs)
        if obs_msg:
            return obs, self._stop(LOOP, obs_msg, "Nhiều lời gọi cho cùng một kết quả. Dịch vụ có đang lỗi không?")

        # --- 3. Bế tắc
        stall = self.loop.check_progress(self.progress())
        if stall:
            return obs, self._stop(STALL, stall, self._stall_question())

        # --- 4. Ngân sách (kiểm cuối cùng)
        return obs, self.check_budget()

    def _stall_question(self) -> str:
        best = max(self.seen_flights.values(), key=self.constraints.score, default=None)
        if best:
            v = self.constraints.check_flight(best)
            return (f"Không có chuyến thỏa hết ràng buộc. Gần nhất là {best['flight_id']} "
                    f"(vi phạm: {'; '.join(v) or 'không'}). Nới ràng buộc nào?")
        return "Chưa tìm được chuyến nào. Đổi ngày hoặc chặng bay?"

    def _check_booking_constraints(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        fid = args.get("flight_id", "")
        flight = self.seen_flights.get(fid)
        if flight is None:
            from tools.mock_database import db
            raw = db.get_flight_by_id(fid)
            flight = {**raw, "price_raw": raw["price"]} if raw else None
        violations = self.constraints.check_flight(flight) if flight else []
        c = self.constraints
        if c.intent in ("lookup", "search", "cancel"):
            violations.append(f"intent: người dùng đang '{c.intent}', chưa yêu cầu đặt vé")
        if c.passenger_name and args.get("passenger_name", "").strip().lower() != c.passenger_name.lower():
            violations.append(f"passenger_name: cần '{c.passenger_name}'")
        if c.passenger_id and str(args.get("passenger_id", "")) != c.passenger_id:
            violations.append(f"passenger_id: cần '{c.passenger_id}'")
        if not args.get("passenger_name") or not args.get("passenger_id"):
            violations.append("thiếu họ tên hoặc CCCD hành khách: phải hỏi người dùng, không được bịa")
        if flight and c.prefer_cheapest:
            best = c.best_candidate(list(self.seen_flights.values()))
            if best and flight.get("price_raw", 0) > best.get("price_raw", 0):
                violations.append(f"prefer_cheapest: {best['flight_id']} rẻ hơn ({best['price_raw']:,})")
        if not violations:
            return None
        best = self.best_candidate()
        return {
            "status": "denied",
            "reason": "constraint_violation",
            "violations": violations,
            "hint": (f"Chuyến hợp lệ tốt nhất đã thấy: {best['flight_id']}" if best
                     else "Chưa có chuyến nào thỏa mọi ràng buộc: báo người dùng, không tự đổi yêu cầu."),
        }

    # ------------------------------------------------------------------ kết thúc lượt
    def completion_report(self) -> Dict[str, Any]:
        return self.completion.check(self.constraints, self.session_bookings, self.user_id)

    def template_answer(self) -> FinalAnswer:
        """Câu trả lời do harness viết từ CSDL (dùng khi output của model không qua kiểm)."""
        rep = self.completion_report()
        b = rep.get("thong_tin_dat_ve")
        if rep["hoan_thanh"] and b:
            return FinalAnswer(
                status="booked", booking_code=b["booking_code"], flight_id=b["flight_id"],
                message=(f"Đặt vé thành công. Mã đặt chỗ {b['booking_code']}, chuyến {b['flight_id']} "
                         f"{b['origin']} -> {b['destination']} ngày {b['date']} lúc {b['departure_time']}, "
                         f"hành khách {b['passenger_name']}, ghế {b['seat_number']}, "
                         f"tổng tiền {b['total_amount']:,} VNĐ."))
        return FinalAnswer(status="error", message="Chưa hoàn thành yêu cầu. Xem thông tin bàn giao để biết bước tiếp theo.")

    def available_options(self) -> List[Dict[str, Any]]:
        """Các chuyến đã thấy, còn chỗ và thỏa mọi ràng buộc (sắp theo giá)."""
        ok = [f for f in self.seen_flights.values()
              if f.get("seats_available", 0) > 0 and not self.constraints.check_flight(f)]
        return sorted(ok, key=lambda f: f.get("price_raw", 0))[:5]

    def options_answer(self) -> Optional[FinalAnswer]:
        """Câu trả lời do code dựng từ kết quả tìm chuyến (dùng khi câu trả lời của model không qua kiểm)."""
        opts = self.available_options()
        if not opts:
            return None
        lines = "; ".join(f"{f['flight_id']} cất cánh {f['departure_time']}, giá {f.get('price_raw', 0):,} VNĐ"
                          for f in opts)
        sold = [fid for fid, f in self.seen_flights.items()
                if f.get("seats_available", 1) == 0 and not self.constraints.check_flight({**f, "seats_available": 1})]
        note = f" Chuyến {', '.join(sold)} đã hết chỗ." if sold else ""
        return FinalAnswer(status="options_found", message=f"Các chuyến còn chỗ phù hợp: {lines}.{note}",
                           suggested_flight_ids=[f["flight_id"] for f in opts])

    def _repair_suggestions(self, answer: FinalAnswer) -> FinalAnswer:
        """Model gợi ý cả chuyến đã hết chỗ: bỏ chuyến đó khỏi danh sách gợi ý thay vì loại cả câu trả lời."""
        sold = [fid for fid in answer.suggested_flight_ids
                if self.seen_flights.get(fid, {}).get("seats_available", 1) == 0]
        if not sold:
            return answer
        keep = [fid for fid in answer.suggested_flight_ids if fid not in sold]
        if not keep and answer.status == "options_found":
            return answer                            # không còn gì để gợi ý -> để validate_answer xử lý
        self.interventions.append({"kind": "SOLD_OUT_SUGGESTION_REMOVED", "reason": ", ".join(sold)})
        return answer.model_copy(update={"suggested_flight_ids": keep})

    def fallback_answer(self, decision: Decision) -> FinalAnswer:
        """FinalAnswer an toàn do code dựng khi model không trả được output hợp lệ."""
        if self.completion_report()["hoan_thanh"]:
            return self.template_answer()
        q = (decision.handoff or {}).get("cau_hoi_cho_nguoi")
        reason = decision.reason or "Không có câu trả lời hợp lệ từ model."
        if decision.kind == ANSWERED and not q:
            options = self.options_answer()          # dựng câu trả lời từ dữ liệu tool thay vì báo lỗi chung chung
            if options:
                return options
        if decision.kind == DENIED:
            return FinalAnswer(status="denied", message=f"Yêu cầu bị từ chối: {reason}")
        if q:
            return FinalAnswer(status="needs_user_input", message=f"Tôi tạm dừng: {reason}", question_for_user=q)
        return FinalAnswer(status="error", message=f"Tôi chưa hoàn thành được yêu cầu: {reason}")

    def finalize(self, answer: FinalAnswer, decision: Decision,
                 structured_attempts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Kiểm output cuối qua 3 lớp: (1)(2) đã đúng schema FinalAnswer (Pydantic) ở phía gọi;
        (3) kiểm nội dung: căn cứ dữ liệu, mã/chuyến có trong kết quả tool, 'booked' phải khớp CSDL."""
        if not isinstance(answer, FinalAnswer):           # chặn mọi đường vòng trả prose
            answer = FinalAnswer.model_validate(answer)
        completion = self.completion_report()
        answer = self._repair_suggestions(answer)
        sources = self.observations + self.user_texts + [json.dumps(self.constraints.to_dict(), ensure_ascii=False)]
        text = answer.message + (" " + answer.question_for_user if answer.question_for_user else "")
        grounding = kiem_can_cu_dat_ve(text, sources)
        semantic = validate_answer(answer, self)
        false_claim = (answer.status == "booked" or phat_hien_tuyen_bo_dat_ve(answer.message)) and not completion["hoan_thanh"]

        raw = answer
        if false_claim:
            self.interventions.append({"kind": "FALSE_CLAIM_BLOCKED", "reason": "Tuyên bố đã đặt nhưng CSDL không có vé hợp lệ"})
            if not decision.stop or decision.kind == ANSWERED:
                decision = self._stop(HUMAN, "FALSE_CLAIM · Model tuyên bố hoàn thành nhưng code kiểm không đạt.",
                                      "Agent báo đã đặt nhưng CSDL không có vé hợp lệ. Kiểm tra lại giao dịch?")
            answer = FinalAnswer(status="error", message="[HARNESS] Câu trả lời bị chặn: model tuyên bố đã đặt vé "
                                 "nhưng CSDL không có vé hợp lệ. " + completion["ly_do"])
        elif semantic or not grounding["dat"]:
            self.interventions.append({"kind": "ANSWER_REJECTED",
                                       "reason": "; ".join(semantic) or f"không nguồn: {grounding['khong_co_nguon']}"})
            answer = self.fallback_answer(decision)

        if decision.kind == ANSWERED and completion["hoan_thanh"]:
            decision.kind = GOAL

        return {
            "answer": answer.model_dump(),
            "final_answer": answer.message + (f"\n❓ {answer.question_for_user}" if answer.question_for_user else ""),
            "raw_answer": raw.model_dump(),
            "answer_validation": {
                "schema_ok": True,
                "structured_attempts": structured_attempts or [],
                "semantic_errors": semantic,
                "grounding_ok": grounding["dat"],
                "replaced_by_harness": answer is not raw,
            },
            "stop": {"kind": decision.kind, "reason": decision.reason,
                     "normal": decision.kind in NORMAL_STOPS},
            "handoff": decision.handoff,
            "completion_report": completion,
            "grounding_report": grounding,
            "false_claim": false_claim,
            "constraints": self.constraints.to_dict(),
            "interventions": list(self.interventions),
            "side_effects": list(self.side_effects),
            "budget": self.budget.snapshot(),
        }
