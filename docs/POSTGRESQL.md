# PostgreSQL cho Module 2

PostgreSQL là nguồn dữ liệu lúc chạy. Docker volume `postgres-data` giữ kịch bản, luật nhận diện và phiên chơi sau khi container được tạo lại. App tạo/migrate schema và nạp dữ liệu mẫu khi khởi động.

## Các bảng

| Bảng | Chứa gì |
| --- | --- |
| `app_users` | Tài khoản với username duy nhất, hash mật khẩu PBKDF2 và vai trò `user`/`admin`; không lưu mật khẩu dạng rõ. |
| `auth_sessions` | Hash token cookie phiên đăng nhập và hạn dùng; token gốc chỉ nằm trong cookie HttpOnly của trình duyệt. |
| `scenarios` | Danh mục kịch bản: ID số, mã ổn định (`bank`), tên, độ khó, số lượt tối đa, điểm bắt đầu, trạng thái; `payload` chỉ giữ cấu hình phụ như nhân vật, dấu hiệu cảnh báo và bài học. |
| `dialogue_nodes` | Node điều khiển hội thoại: stage, mục tiêu, thủ đoạn, hành động được yêu cầu và timeout. Nội dung câu nói nằm tập trung trong `dialogue_lines`. Mỗi kịch bản có một node bắt đầu và ba node kết thúc. |
| `dialogue_lines` | Danh mục tập trung cho câu cố định và câu LLM. `source` phân biệt `fixed`/`llm`; câu LLM có nhãn intent, khóa câu người chơi, model/prompt, cờ bật/tắt, số lượt dùng và `preference_score`. Điểm ưu tiên được cập nhật trực tiếp trên dòng này. Mỗi tình huống có 12 biến thể mở đầu cố định, được chọn luân phiên theo `use_count`. |
| `dialogue_transitions` | Một dòng cho mỗi cặp `(node hiện tại, intent)`, trỏ tới node kế tiếp và chứa thay đổi điểm/phản hồi. |
| `intent_phrase_rules` | Cụm từ bổ sung cho bộ nhận diện. `scenario_id = NULL` nghĩa là dùng chung; nếu có ID thì chỉ dùng cho kịch bản đó. `priority` lớn hơn được xét trước. |
| `intent_defaults` | Luật chung cho `hang_up`, `share_sensitive`, `transfer_money` và `unknown`, tránh lặp nhánh kết thúc ở mọi node. |
| `call_sessions` | Phiên chơi dùng chung cho cả nhắn tin và cuộc gọi; `interaction_mode` ghi nguồn (`message`/`call`), `opening_line_id` lưu chính xác câu mở đầu đã chọn, cùng chủ sở hữu, node hiện tại, điểm, số lượt, trạng thái và kết quả. Phiên cũ được gán `message` khi migration; phiên chưa gắn chủ sở hữu vẫn được giữ nhưng không hiện trong lịch sử tài khoản mới. |
| `call_turns` | Mỗi lượt: node máy vừa nói, nhãn nhận diện, điểm/phản hồi, văn bản bot đã gửi và ID câu trong `dialogue_lines` nếu là câu LLM. Văn bản người chơi được lưu dưới dạng đã che dãy số dài. |
| `intent_review_candidates` | Câu `unknown` hoặc câu người chơi báo máy hiểu sai, đã che thông tin, ngữ cảnh, đề xuất từ LLM và trạng thái chờ duyệt. Duyệt mới tạo luật hoạt động; từ chối thì không ảnh hưởng bộ nhận diện. |

`scenarios.payload` không còn chứa bản sao của `stages` và `scoring`. Hai phần đó được đồng bộ từ các file JSON `data/scenarios/` vào `dialogue_nodes` và `dialogue_transitions` mỗi lần app khởi động. JSON là nguồn chuẩn cho metadata node và nhánh; câu cố định đã có không bị ghi đè.

Các biến thể mở đầu nằm trong `data/opening_line_variants.json` (12 câu cho mỗi kịch bản, gồm câu gốc). Khi khởi động, seed thêm câu còn thiếu mà không ghi đè câu đã có. Mỗi phiên mới chọn câu có `use_count` thấp nhất; `call_sessions.opening_line_id` giữ lại đúng câu đã hiển thị trong transcript.

## Nạp dữ liệu và cập nhật

App đọc `data/scenarios/*.json` khi khởi động để tạo mới hoặc đồng bộ metadata node, transition, điểm thay đổi và timeout. Seed/migration chạy idempotent: không tạo trùng node hay câu thoại khi khởi động lại. Thay đổi diễn biến trong JSON sẽ có hiệu lực sau khi khởi động lại container; câu thoại cố định và câu LLM đã lưu trong `dialogue_lines` vẫn được giữ nguyên.

Các migration schema chạy trong transaction khi app khởi động. Migration chuyển cấu trúc cũ sang các bảng mới và giữ lại nội dung kịch bản, trạng thái, điểm cùng luật ý định hiện có.

## Luồng API

- `POST /api/arena/calls` với `{"scenario_key":"bank"}` tạo phiên và trả node bắt đầu.
- `POST /api/arena/calls/{session_id}/turn` gửi `user_text` và `elapsed_seconds`; server phân loại intent, chọn transition/default, tính điểm và lưu lượt.
- `POST /api/arena/calls/{session_id}/finish` kết thúc thủ công phiên đang mở.
- `GET /api/arena/calls/{session_id}/summary` trả điểm, phản hồi theo lượt, dấu hiệu cảnh báo và bài học.
- `GET /api/arena/history` liệt kê phiên gần đây; `GET /api/arena/calls/{session_id}/transcript` trả hội thoại đã che.
- `POST /api/arena/calls/{session_id}/turns/{turn_no}/flag` đưa lượt người chơi báo hiểu sai vào hàng đợi phân tích.
- `GET /api/arena/admin/intent-candidates` liệt kê câu chờ duyệt. `POST .../{candidate_id}/approve` thêm phrase rule theo kịch bản; `POST .../{candidate_id}/reject` bỏ qua đề xuất.

Nhận diện trong lúc chơi hiện dùng luật trong Python và cụm từ trong database. Khi chưa có luật phù hợp hoặc các luật mâu thuẫn, kết quả là `unknown`; `intent_method` ghi `fallback`. Sau khi kết thúc phiên, các câu `unknown` được đưa vào `intent_review_candidates`; người chơi cũng có thể báo lượt máy phân loại sai từ lịch sử để đưa câu đó vào hàng đợi. Nếu cấu hình `OPENAI_API_KEY`, backend gửi câu đã che số dài/email cùng câu thoại và hành động được yêu cầu tới Responses API để đề xuất ý định/cụm từ. Không có key thì admin có thể gán nhãn thủ công. LLM không được quyền thêm hoặc bật luật; các API duyệt yêu cầu tài khoản admin. Compose mặc định bind port trên localhost; khi đưa lên mạng, hãy bật HTTPS và cookie Secure.

Trước khi lưu câu trả lời, backend thay mọi dãy từ 4 chữ số trở lên bằng `****`. Không lưu bản gốc câu trả lời trong `call_turns`. Thời gian phản hồi được lưu riêng để tính chỉ số tham khảo.

## Tài khoản và quyền truy cập

Các endpoint tài khoản: `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout` và `GET /api/auth/me`. Cookie đăng nhập HttpOnly, SameSite=Lax, hết hạn sau 14 ngày. Mật khẩu tài khoản tối thiểu 3 ký tự và được băm PBKDF2.

API phiên chơi, lịch sử, transcript, ghi âm và đọc thoại yêu cầu đăng nhập, đồng thời kiểm tra chủ sở hữu phiên. `/api/arena/scenarios` vẫn công khai để tải danh sách tình huống. Lịch sử cũ có `user_id IS NULL` được giữ lại nhưng không tự gán cho tài khoản nào. Câu thoại và điểm ưu tiên trong `dialogue_lines` dùng chung giữa người dùng, tin nhắn và cuộc gọi.

Đăng ký tài khoản qua ứng dụng như bình thường, sau đó cấp quyền quản trị trực tiếp trong PostgreSQL:

```sql
UPDATE app_users SET role = 'admin' WHERE username = 'ten_dang_nhap' RETURNING username, role;
```

Để gỡ quyền admin, đổi role về `user`. Không có tài khoản admin mặc định và ứng dụng không tự thay đổi role khi khởi động. API quản trị kiểm tra role hiện tại trong database. Tải lại trang hoặc đăng nhập lại để giao diện cập nhật quyền mới. Khi triển khai sau HTTPS, đặt `AUTH_COOKIE_SECURE=true`.

## Xem dữ liệu

```powershell
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT scenario_id, scenario_name, title, status FROM scenarios ORDER BY scenario_id;"
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT scenario_id, node_key, stage, is_start, is_terminal FROM dialogue_nodes ORDER BY scenario_id, node_id;"
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT from_node_id, intent, to_node_id, score_delta FROM dialogue_transitions ORDER BY from_node_id, intent;"
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT id, scenario_id, intent, phrase, match_type, priority, enabled FROM intent_phrase_rules ORDER BY priority DESC, id;"
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT session_id, scenario_id, outcome, total_score, turn_no FROM call_sessions ORDER BY started_at DESC;"
docker compose exec db psql -U scam_arena -d scam_arena -c "SELECT session_id, turn_no, user_text_masked, intent, score_delta, feedback FROM call_turns ORDER BY created_at DESC;"
```

## Thêm luật nhận diện

Thêm một dòng vào `intent_phrase_rules` hoặc duyệt một đề xuất ở trang chủ. Cụm dùng `contains` sẽ so khớp sau khi bỏ dấu và chuẩn hóa khoảng trắng; `regex` chạy biểu thức chính quy trên câu đã chuẩn hóa NFC/chữ thường. `phrase_norm` là cụm đã bỏ dấu, chữ thường; hãy cập nhật cột này cùng `phrase` khi sửa luật. Khi duyệt qua UI, cache luật được làm mới tự động. Sau khi sửa trực tiếp bằng SQL, khởi động lại app để xóa cache luật:

```powershell
docker compose restart scam-arena
```

Khu vực duyệt phrase rules trên trang chủ là công cụ nội bộ không có đăng nhập, phù hợp khi chạy local. Không đưa lên máy chủ công khai trước khi có xác thực và phân quyền. Sinh lời thoại thử lần lượt Gemini, Groq, rồi OpenRouter khi provider trước lỗi/hết quota. Cấu hình qua `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` và model tương ứng; bật `LINE_LLM_ENABLED=true`. Sau khi sửa `.env`, chạy `docker compose up -d --build --force-recreate scam-arena`. Rà soát ý định sau phiên vẫn dùng `OPENAI_API_KEY` riêng. Compose mặc định dùng PostgreSQL local; có thể đặt `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` trong `.env` trước lần chạy đầu. Đổi mật khẩu trong `.env` không tự sửa thông tin của volume đã khởi tạo.
# Unified dialogue line catalog

`dialogue_lines` là nơi lưu nội dung câu thoại duy nhất: câu cố định của node và câu LLM đều gắn với `node_id`. Câu LLM được phân biệt bằng `source='llm'`; cache dùng `intent`, `is_reprompt`, `player_text_norm` và `prompt_version`. Lượt thích tăng `preference_score`, yêu cầu tạo lại giảm điểm câu cũ trực tiếp trong cùng bảng; không còn bảng feedback riêng. Migration chuyển các câu và điểm từ `generated_lines`, chuyển văn bản cố định khỏi `dialogue_nodes`, cập nhật liên kết lượt rồi xóa bảng/cột cũ. `call_turns` giữ `bot_reply_text` làm ảnh chụp nội dung đã gửi và `line_id` làm liên kết tới câu LLM. `call_sessions.interaction_mode` chỉ để phân tích theo kênh, cache vẫn dùng chung.

```sql
SELECT line_source, count(*) AS turns,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS percent
FROM call_turns WHERE line_source IS NOT NULL GROUP BY line_source;
SELECT line_source, round(avg(line_latency_ms)::numeric, 1) AS avg_latency_ms
FROM call_turns WHERE line_source IS NOT NULL GROUP BY line_source;
UPDATE dialogue_lines SET enabled = FALSE WHERE line_id = 123;
```

Pre-warm lời thoại bằng `docker compose exec scam-arena python -m app.arena.prewarm_lines --scenario bank` (thay `bank` bằng scenario key). Cần đặt `GEMINI_API_KEY` và bật `LINE_LLM_ENABLED=true` trước khi chạy.
