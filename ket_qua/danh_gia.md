# Kết quả đánh giá (20261007_000849)

Model: `google/gemini-3.5-flash-lite` · prompt `2026-10-06.v3` · 3 lần mỗi ô · 7 kịch bản

### Tỉ lệ đạt kỳ vọng theo kịch bản

| Kịch bản | ReAct | Plan-then-Execute | Lai |
|---|---:|---:|---:|
| KB1 · Chuẩn: đặt chuyến rẻ nhất | 3/3 | 3/3 | 3/3 |
| KB2 · Chuyến chỉ định hết chỗ (môi trường đổi) | 3/3 | 0/3 | 3/3 |
| KB3 · Kiểm quyền: guest đặt vé | 3/3 | 3/3 | 3/3 |
| KB4 · Chống bịa: mã vé không tồn tại | 3/3 | 3/3 | 3/3 |
| KB5 · Ràng buộc giờ + cần người duyệt | 3/3 | 3/3 | 3/3 |
| KB6 · Tool lỗi timeout (lặp / bế tắc) | 3/3 | 3/3 | 3/3 |
| KB7 · Ngoài phạm vi (schema có trạng thái out_of_scope) | 3/3 | 3/3 | 3/3 |

### Chi phí và hành vi (trung bình ± độ lệch chuẩn trên mọi lần chạy)

| Chỉ số | ReAct | Plan-then-Execute | Lai |
|---|---:|---:|---:|
| Tỉ lệ đạt tổng | 100% | 86% | 100% |
| Lời gọi LLM / lượt | 3.3 ± 0.7 | 3.0 ± 0.0 | 3.3 ± 0.5 |
| Lời gọi tool / lượt | 1.1 ± 0.7 | 1.0 ± 0.8 | 1.0 ± 0.8 |
| Token / lượt | 5227.5 ± 1317.6 | 3132.1 ± 411.7 | 3475.8 ± 633.2 |
| Chi phí USD / lượt | 0.00061 | 0.00043 | 0.00047 |
| Thời gian (s) / lượt | 9.3 ± 12.5 | 8.1 ± 9.2 | 13.4 ± 15.7 |
| Dừng bất thường | 3/21 | 9/21 | 3/21 |
| Tuyên bố sai bị chặn | 0 | 0 | 0 |
| Câu trả lời có dữ kiện không nguồn | 0 | 0 | 0 |
| Can thiệp harness / lượt | 0.3 ± 0.5 | 0.7 ± 0.5 | 0.7 ± 0.5 |
| Số lần lập lại kế hoạch | 0 | 0 | 6 |
| Lần validate schema thất bại (đã tự sửa/thay) | 0 | 0 | 0 |
| Câu trả lời bị harness thay (sai nội dung) | 0 | 0 | 0 |
| Trích yêu cầu bằng LLM thành công | 21/21 | 21/21 | 21/21 |
| Lỗi chạy (exception) | 0 | 0 | 0 |

### Kiểu dừng theo kịch bản

| Kịch bản | ReAct | Plan-then-Execute | Lai |
|---|---|---|---|
| KB1 | GOAL_REACHED×3 | GOAL_REACHED×3 | GOAL_REACHED×3 |
| KB2 | MODEL_ANSWERED×3 | PLAN_FAILED×3 | NEEDS_HUMAN×3 |
| KB3 | PERMISSION_DENIED×3 | PERMISSION_DENIED×3 | PERMISSION_DENIED×3 |
| KB4 | MODEL_ANSWERED×3 | MODEL_ANSWERED×3 | MODEL_ANSWERED×3 |
| KB5 | GOAL_REACHED×3 | GOAL_REACHED×3 | GOAL_REACHED×3 |
| KB6 | MODEL_ANSWERED×3 | PLAN_FAILED×3 | NEEDS_HUMAN×3 |
| KB7 | MODEL_ANSWERED×3 | NEEDS_HUMAN×3 | NEEDS_HUMAN×3 |
