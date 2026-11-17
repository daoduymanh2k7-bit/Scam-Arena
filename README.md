# Scam Arena

Scam Arena là ứng dụng luyện phản xạ nhận biết và xử lý các tình huống lừa đảo giả lập bằng tiếng Việt. Người chơi trò chuyện với nhân vật gọi điện giả lập, trả lời bằng bàn phím hoặc giọng nói, rồi xem nhãn hệ thống nhận diện, điểm số và phản hồi sau từng lượt.

> Đây là công cụ đào tạo với nội dung giả lập, không phải dịch vụ ngân hàng, cơ quan công an hay tư vấn xử lý sự cố thật.

## Mục lục

- [Tính năng](#tính-năng)
- [Yêu cầu](#yêu-cầu)
- [Chạy nhanh bằng Docker Desktop](#chạy-nhanh-bằng-docker-desktop)
- [Cấu hình](#cấu-hình)
- [Sử dụng ứng dụng](#sử-dụng-ứng-dụng)
- [LLM và lời thoại](#llm-và-lời-thoại)
- [Nhận diện ý định và chấm điểm](#nhận-diện-ý-định-và-chấm-điểm)
- [Dữ liệu và sao lưu](#dữ-liệu-và-sao-lưu)
- [Sơ đồ kịch bản](#sơ-đồ-kịch-bản)
- [Chạy kiểm tra và tiền tạo cache](#chạy-kiểm-tra-và-tiền-tạo-cache)
- [Chạy không dùng Docker](#chạy-không-dùng-docker)
- [Cấu trúc dự án](#cấu-trúc-dự-án)
- [Đưa ứng dụng lên Internet](#đưa-ứng-dụng-lên-internet)
- [Giới hạn đã biết](#giới-hạn-đã-biết)
- [Tài liệu bổ sung](#tài-liệu-bổ-sung)

## Tính năng

- Ba kịch bản mẫu: giả nhân viên ngân hàng, giả trúng thưởng và giả công an điều tra.
- Mỗi tình huống có 12 biến thể lời mở đầu để tránh lặp câu giống hệt qua các phiên. Câu đã chọn được lưu theo phiên.
- Nhắn tin và giao diện cuộc gọi dùng chung kịch bản, tài khoản, PostgreSQL, lịch sử và kho câu thoại. Giao diện cuộc gọi hiện là mô phỏng; không thực hiện cuộc gọi điện thoại thật.
- Nhập câu trả lời bằng bàn phím hoặc ghi âm. Whisper nhận dạng tiếng Việt; Piper đọc lời thoại bằng tiếng Việt.
- Hiển thị nhãn ý định được nhận diện, phương thức nhận diện, nguồn lời thoại (luật/cố định/LLM/cache) và độ trễ.
- Người chơi có thể yêu cầu tạo lại câu trả lời hoặc thích câu hiện tại. Tạo lại giảm điểm ưu tiên câu cũ; thích câu tăng điểm ưu tiên. Kho câu dùng chung giữa người dùng.
- Đăng ký, đăng nhập và lịch sử theo tài khoản. Các tài khoản dùng chung database và nội dung cache; mỗi người chỉ truy cập phiên của chính mình.
- Bộ phân loại Rasa và các luật an toàn xác định ý định; khi kết quả là `unknown`, LLM có thể phân loại lại trước khi hệ thống chọn nhánh và chấm điểm. Các hành vi nhạy cảm như tiết lộ mã hoặc chuyển tiền vẫn do luật an toàn kiểm tra.
- API xem xét câu chưa nhận diện dành cho tài khoản admin; đề xuất của LLM không tự trở thành luật cho đến khi được duyệt.

## Yêu cầu

- Windows 10/11, macOS hoặc Linux.
- Docker Desktop đang chạy ở chế độ Linux containers, có Docker Compose v2.
- Internet trong lần build/tải model đầu tiên.
- RAM và dung lượng đĩa đủ cho image Rasa, Whisper và dữ liệu PostgreSQL. Lần build Rasa đầu tiên có thể tải image lớn và train NLU model.
- API key của ít nhất một nhà cung cấp Gemini, Groq hoặc OpenRouter nếu muốn sinh thoại LLM. Ứng dụng vẫn chạy với lời thoại cố định khi không cấu hình LLM.

## Chạy nhanh bằng Docker Desktop

Các lệnh dưới đây dùng PowerShell tại thư mục gốc repository.

### 1. Tạo file cấu hình local

```powershell
Copy-Item .env.example .env
```

Mở `.env` bằng VS Code hoặc trình soạn thảo. Không commit hoặc gửi file này cho người khác vì nó có thể chứa API key và mật khẩu database.

### 2. Build image

```powershell
docker compose build
```

Nếu lệnh báo không kết nối được Docker Engine, hãy mở Docker Desktop, chờ trạng thái Engine chạy rồi thử lại.

### 3. Tải giọng đọc Piper

```powershell
docker compose run --rm scam-arena python -m piper.download_voices vi_VN-vais1000-medium --download-dir /app/voices
```

File giọng đọc được lưu trong thư mục `voices/` trên máy. Nếu chỉ muốn dùng bàn phím và không cần đọc lời thoại thành tiếng, có thể bỏ qua bước này.

### 4. Khởi động ứng dụng

```powershell
docker compose up -d
```

Compose chạy ba dịch vụ: `scam-arena` (web/API), `db` (PostgreSQL) và `rasa` (nhận diện ý định). Chờ các container chuyển sang `Healthy` hoặc `Running`.

### 5. Mở web và kiểm tra

- Ứng dụng: [http://localhost:8000](http://localhost:8000)
- Health check: [http://localhost:8000/health](http://localhost:8000/health)
- Sơ đồ kịch bản: [http://localhost:8000/scenario-map.html](http://localhost:8000/scenario-map.html)

Health check trả `{"status":"ok"}` khi API sẵn sàng. Đăng ký tài khoản ngay trên màn hình đầu tiên để bắt đầu.

### Lệnh vận hành thường dùng

```powershell
# Xem trạng thái
docker compose ps

# Xem log web/API
docker compose logs -f scam-arena

# Xem log Rasa
docker compose logs -f rasa

# Khởi động lại web sau khi sửa mã hoặc .env
docker compose up -d --build scam-arena

# Dừng các container, giữ nguyên database và model đã tải
docker compose down
```

Để áp dụng thay đổi `.env`, tạo lại container:

```powershell
docker compose up -d --force-recreate scam-arena
```

Để xóa dữ liệu database và bắt đầu lại từ đầu, thao tác này sẽ xóa vĩnh viễn lịch sử, tài khoản và cache:

```powershell
docker compose down -v
```

## Cấu hình

Compose tự đọc `.env` ở thư mục gốc. Các giá trị mặc định dưới đây phù hợp chạy local; phải thay mật khẩu mặc định trước khi triển khai cho người khác.

| Biến | Mặc định | Mục đích |
| --- | --- | --- |
| `POSTGRES_DB` | `scam_arena` | Tên database PostgreSQL. |
| `POSTGRES_USER` | `scam_arena` | Tài khoản database. |
| `POSTGRES_PASSWORD` | `scam_arena_local_dev` | Mật khẩu database; hãy đổi thành chuỗi mạnh, URL-safe. |
| `LINE_LLM_ENABLED` | `false` trong Compose | Bật sinh lời thoại và phân loại lại `unknown` khi là `true` hoặc `1`. |
| `GEMINI_API_KEY` | rỗng | Key Gemini; provider ưu tiên đầu tiên. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model Gemini. |
| `GROQ_API_KEY` | rỗng | Key Groq; provider dự phòng sau Gemini. |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | Model Groq. |
| `OPENROUTER_API_KEY` | rỗng | Key OpenRouter; provider dự phòng sau Groq. |
| `OPENROUTER_MODEL` | `openrouter/free` | Model OpenRouter. |
| `LINE_LLM_TIMEOUT_SECONDS` | `3` | Timeout cho mỗi yêu cầu LLM. |
| `LINE_POOL_SIZE` | `5` | Số câu tối thiểu trong kho cho mỗi nhóm cache trước khi ngừng gọi LLM. |
| `LINE_PROMPT_VERSION` | `v2` | Phiên bản prompt, đồng thời tách các nhóm cache theo prompt. |
| `WHISPER_MODEL` | `base` | Model Whisper chạy local (`base`, `small`, ... tùy tài nguyên máy). |
| `RASA_NLU_TIMEOUT_SECONDS` | `2` | Timeout gọi dịch vụ Rasa nội bộ. |
| `PIPER_SENTENCE_PAUSE_MS` | `350` | Khoảng nghỉ giữa câu khi Piper đọc. |
| `AUTH_COOKIE_SECURE` | `false` | Đặt `true` khi phục vụ qua HTTPS. |

Để bật Gemini và dự phòng Groq rồi OpenRouter, điền key tương ứng trong `.env` và đặt:

```dotenv
LINE_LLM_ENABLED=true
GEMINI_API_KEY=...
GROQ_API_KEY=...
OPENROUTER_API_KEY=...
```

Không cần khai báo provider mà bạn không dùng; xóa key khỏi `.env` hoặc để trống sẽ bỏ qua provider đó. Sau khi cập nhật, tạo lại container như hướng dẫn ở trên. API key không được lưu vào PostgreSQL hay gửi tới trình duyệt; chỉ backend sử dụng chúng khi gọi dịch vụ.

### Tài khoản

- Username: 3–32 ký tự, chữ Latin, số, dấu chấm, gạch dưới hoặc gạch ngang.
- Mật khẩu: tối thiểu 3 ký tự; mật khẩu được băm trước khi lưu.
- Phiên đăng nhập tồn tại tối đa 14 ngày.
- Tài khoản thường chỉ xem lịch sử và transcript của chính mình.
- Muốn cấp quyền admin, tạo tài khoản bình thường rồi đổi `role` trong PostgreSQL. Ví dụ:

  ```sql
  UPDATE app_users SET role = 'admin' WHERE username = 'ten_dang_nhap' RETURNING username, role;
  ```

  Hạ quyền lại bằng `UPDATE app_users SET role = 'user' WHERE username = 'ten_dang_nhap';`. Tải lại trang hoặc đăng nhập lại để giao diện hiện quyền mới. Không có tài khoản admin mặc định được tạo lúc khởi động.

## Sử dụng ứng dụng

1. Tạo tài khoản hoặc đăng nhập.
2. Chọn một tình huống. Mỗi phiên được chọn một biến thể mở đầu từ kho câu cố định.
3. Trả lời trong khung nhập hoặc cấp quyền micro để ghi âm. Trình duyệt thường chỉ cho phép micro trên `localhost` hoặc website HTTPS.
4. Sau phản hồi, xem nhãn nhận diện bên dưới câu người chơi. Di chuột lên biểu tượng `i` ở cuối tin nhắn bot để xem nguồn câu và độ trễ.
5. Mở rộng câu bot để dùng nút **Trả lời lại câu này** hoặc **Thích câu này**. Các nút phản hồi cập nhật độ ưu tiên trong kho dùng chung.
6. Kết thúc phiên để xem điểm, phản hồi và lưu transcript vào lịch sử tài khoản.

Chọn chế độ **Cuộc gọi** hoặc **Nhắn tin** trên giao diện. Hai chế độ ghi cùng loại phiên và dùng chung kịch bản, điểm, cache và PostgreSQL; chế độ cuộc gọi hiện là giao diện mô phỏng chứ chưa gọi qua mạng điện thoại.

## LLM và lời thoại

LLM chỉ viết câu phản hồi cho node đã được hệ thống chọn. Nó không tự chọn nhánh, không tự tính điểm và không kết thúc phiên. Lời mở đầu dùng các biến thể cố định trong `data/opening_line_variants.json`; node kết thúc cũng dùng lời cố định.

Khi `LINE_LLM_ENABLED=true`, backend thử lần lượt Gemini → Groq → OpenRouter theo các key được cấu hình. Câu hợp lệ được lưu cùng cache PostgreSQL, ngữ cảnh intent và node; các lượt sau tái sử dụng cache. `LINE_POOL_SIZE` đặt ngưỡng số biến thể trong cùng nhóm trước khi ngừng yêu cầu câu mới. Tương tác thích/thử lại làm tăng/giảm `preference_score` để ảnh hưởng thứ tự chọn câu trong kho.

Khi bộ nhận diện trả `unknown`, backend có thể hỏi các provider theo cùng thứ tự. Chỉ những nhãn an toàn có độ tin cậy đủ cao mới được dùng thay nhãn ban đầu; nhãn mới được đưa vào bước chọn transition và tính điểm. Phân loại lại không thể gán nhãn `share_sensitive` hoặc `transfer_money`; các hành vi đó phải được xác nhận bằng luật an toàn. Nếu LLM tắt, hết quota, timeout hoặc lỗi, hệ thống tiếp tục bằng kết quả luật hiện có.

Đầu vào gửi cho LLM dùng nội dung đã che số dài và email. Câu sinh ra được kiểm tra trước khi lưu. Nếu LLM không sẵn sàng, câu cố định được dùng để luồng chơi tiếp tục. Sinh câu LLM có thể làm lượt chơi chậm hơn tới timeout cấu hình cho mỗi lần thử provider.

### Tiền tạo câu thoại cache

Khi app đang chạy và LLM đã cấu hình, có thể tiền tạo kho cho một tình huống:

```powershell
docker compose exec scam-arena python -m app.arena.prewarm_lines --scenario bank
```

Thay `bank` bằng `lottery` hoặc `police`. Có thể giới hạn số câu tạo trong một kho bằng `--per-pool N`. Việc này gọi API provider và có thể tiêu tốn quota/chi phí. Câu mở đầu được seed riêng, không cần prewarm.

## Nhận diện ý định và chấm điểm

Hệ thống hiện hỗ trợ 8 nhãn: `verify`, `refuse`, `doubt`, `comply`, `share_sensitive`, `transfer_money`, `hang_up`, `unknown`.

Luật an toàn tất định kiểm tra hành vi nguy hiểm, sau đó Rasa phân loại ngôn ngữ tự nhiên; luật phrase trong PostgreSQL hỗ trợ các trường hợp dự phòng. Nếu kết quả vẫn `unknown` và LLM được bật, bộ phân loại LLM chỉ có thể đổi sang một trong các nhãn an toàn. Cùng một nhãn cuối cùng được dùng cho cả transition và điểm, tránh việc phân loại và chấm điểm tự mâu thuẫn.

Đồ thị nhánh và điểm được cấu hình trong các file scenario JSON lúc seed vào PostgreSQL. Dòng trong `dialogue_transitions` ánh xạ `(node hiện tại, intent)` tới node tiếp theo cùng điểm thay đổi và phản hồi. LLM viết lời thoại sau khi code chọn node đích; thay đổi prompt không làm thay đổi đồ thị.

## Dữ liệu và sao lưu

PostgreSQL là nguồn dữ liệu lúc chạy. Docker volume `postgres-data` giữ tài khoản, phiên, transcript, luật, câu thoại và điểm ưu tiên qua các lần build/restart. `whisper-cache` giữ model Whisper; thư mục `voices/` giữ model Piper.

Các bảng chính:

- `app_users`, `auth_sessions`: tài khoản và phiên đăng nhập.
- `scenarios`, `dialogue_nodes`, `dialogue_transitions`: metadata, node hội thoại, nhánh và điểm.
- `dialogue_lines`: toàn bộ nội dung câu cố định và câu LLM, lượt dùng, trạng thái bật/tắt và điểm ưu tiên.
- `call_sessions`, `call_turns`: phiên chơi, câu trả lời đã che thông tin, intent, điểm và transcript.
- `intent_phrase_rules`, `intent_defaults`: luật nhận diện bổ sung và luật mặc định.
- `intent_review_candidates`: đề xuất intent cần admin xem xét.

Migration và seed được chạy idempotent khi ứng dụng khởi động. Các node, metadata và transition của kịch bản đã published được đồng bộ từ `data/scenarios/*.json` mỗi lần khởi động; vì vậy sửa diễn biến trong các file này sẽ cập nhật nhánh đang chạy. Câu thoại cố định đã có trong database không bị ghi đè; các câu thoại mới được thêm nếu còn thiếu. Phrase rules và 12 câu mở đầu mỗi tình huống được nạp idempotent từ `data/intent_phrases.json` và `data/opening_line_variants.json`.

Sao lưu database ra file SQL:

```powershell
docker compose exec -T db pg_dump -U scam_arena -d scam_arena > scam-arena-backup.sql
```

Khôi phục vào database local đang chạy:

```powershell
Get-Content scam-arena-backup.sql | docker compose exec -T db psql -U scam_arena -d scam_arena
```

Nếu đã đổi `POSTGRES_USER` hoặc `POSTGRES_DB`, thay tham số tương ứng. Không xóa volume `postgres-data` nếu còn cần giữ dữ liệu.

Xem thêm lệnh SQL và mô tả schema trong [`docs/POSTGRESQL.md`](docs/POSTGRESQL.md).

## Sơ đồ kịch bản

Sơ đồ HTML được tạo tự động khi app khởi động. Có thể tạo lại thủ công bằng Python 3.11+:

```powershell
python backend/app/scenario_visualizer.py
```

Mở `frontend/static/scenario-map.html` trong trình duyệt hoặc vào `http://localhost:8000/scenario-map.html`. Trang tải Mermaid từ CDN, do đó cần Internet để hiển thị sơ đồ. Hướng dẫn cấu trúc scenario nằm tại [`docs/SCENARIO_SCHEMA.md`](docs/SCENARIO_SCHEMA.md).

## Chạy kiểm tra và tiền tạo cache

Nếu đã cài `requirements-dev.txt`, chạy test backend bằng:

```powershell
$env:PYTHONPATH = "backend"
python -m pytest backend/tests -q
```

Một số test cần mock dịch vụ ngoài để không gọi mạng hoặc tiêu quota. Để chỉ kiểm tra parser Python:

```powershell
python -m compileall backend/app
```

## Chạy không dùng Docker

Đây là chế độ phát triển nâng cao. Cần cài PostgreSQL, tạo database theo cấu hình, chạy Rasa NLU tại địa chỉ cấu hình `RASA_NLU_URL`, cài Python 3.12+, rồi tải model Piper vào `voices/`.

Trong PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m piper.download_voices vi_VN-vais1000-medium --download-dir voices
$env:PYTHONPATH = "backend"
$env:DATABASE_URL = "postgresql://scam_arena:scam_arena_local_dev@localhost:5433/scam_arena"
python -m uvicorn app.main:app --app-dir backend --reload
```

Các biến provider, Rasa và auth cần được đặt trong môi trường shell hoặc `.env` được nạp trước khi chạy. Mở `http://127.0.0.1:8000`.

## Cấu trúc dự án

```text
backend/app/
├── api/                    # HTTP routes cho arena, xác thực và voice
├── arena/                  # hội thoại, intent, chấm điểm, cache/generate lời thoại
├── voice/                  # nhận dạng Whisper và TTS Piper
├── auth.py                 # tài khoản, cookie phiên, phân quyền admin
├── database.py             # pool PostgreSQL, DDL, migration và seed
└── main.py                 # FastAPI app và lifecycle
backend/tests/               # test backend
data/scenarios/              # kịch bản JSON nguồn
data/opening_line_variants.json # 12 câu mở đầu mỗi tình huống
frontend/static/             # giao diện web
rasa/                        # cấu hình và dữ liệu huấn luyện Rasa
compose.yaml                 # các dịch vụ Docker Compose
Dockerfile                   # image web/API
docs/                        # schema, PostgreSQL và thiết kế nhận diện
```

## Đưa ứng dụng lên Internet

Compose mặc định chỉ bind web vào `127.0.0.1:8000` và database vào `127.0.0.1:5433`, không mở trực tiếp các cổng này ra mạng công cộng. Để chia sẻ an toàn cần reverse proxy/tunnel HTTPS, đặt `AUTH_COOKIE_SECURE=true`, đổi mật khẩu PostgreSQL, cấu hình admin mạnh nếu cần, và bảo vệ backup database/API keys. Không đưa `.env` lên GitHub.

Khi public, tất cả người dùng dùng chung database và kho câu thoại. Mỗi người chỉ xem phiên của tài khoản mình; các câu thoại và điểm ưu tiên là dữ liệu chung. Cần giám sát dung lượng database, quota nhà cung cấp LLM, chi phí, log và tốc độ gọi API. Không nên dùng database local mặc định cho môi trường công khai.

## Giới hạn đã biết

- Chế độ cuộc gọi là giao diện mô phỏng, chưa khởi tạo cuộc gọi điện thoại thực.
- LLM là tùy chọn; API key có thể hết quota hoặc provider lỗi. Khi lỗi, hệ thống dùng lời thoại cố định hoặc giữ nhãn luật để phiên tiếp tục.
- Provider free có thể giới hạn quota, tốc độ, model khả dụng và định dạng JSON; fallback không đảm bảo luôn sinh được câu.
- Whisper chạy CPU mặc định với model `base`, cần tải model lần đầu và có thể làm chậm lần ghi âm đầu tiên.
- Piper cần file voice trong `voices/`; nếu chưa tải voice, nhập bàn phím vẫn dùng được nhưng TTS không hoạt động.
- Rasa chạy trong container riêng; build đầu tải image lớn và train model. Các câu huấn luyện chưa phải kết quả đánh giá độ chính xác production.
- Tài khoản chưa có xác minh email hoặc tự khôi phục mật khẩu. Quên mật khẩu cần quản trị viên xử lý.
- Các biến thể lời mở đầu và câu thoại cố định đã có được lưu trong PostgreSQL; thêm biến thể mới vào JSON sẽ nạp câu còn thiếu khi ứng dụng khởi động, không xóa các câu cũ.
- Đây là bản thực hành; không dùng dữ liệu cá nhân thật, OTP thật, thông tin tài khoản thật hoặc nội dung liên hệ tổ chức thật trong kịch bản.

## Tài liệu bổ sung

- [Schema PostgreSQL](docs/POSTGRESQL.md)
- [Schema kịch bản](docs/SCENARIO_SCHEMA.md)
- [Thiết kế và nhãn nhận diện intent](docs/INTENT_DETECTION.md)
- [JSON Schema kịch bản](docs/scenario.schema.json)
