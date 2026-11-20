# whisper.cpp lượng tử hóa cho Scam Arena

Mặc định mới: `STT_PROVIDER=whisper_cpp`, model Whisper **base đa ngôn ngữ Q8_0**.
Đây là thay engine nhận diện, không huấn luyện lại Rasa và không thay đổi schema DB.

## Lượng tử hóa đang được áp dụng thế nào?

| File chính thức | Kích thước file | Mục đích |
| --- | --- | --- |
| `ggml-base.bin` | khoảng 148 MB | Bản thường để tham khảo kích thước |
| `ggml-base-q8_0.bin` | 81.768.585 byte | Mặc định; chọn mức lượng tử ít mạnh hơn Q5 để ưu tiên giữ chất lượng |
| `ggml-base-q5_1.bin` | 59.707.625 byte | Tùy chọn nhẹ hơn để thử nghiệm |

Kích thước file không phải tổng RAM khi nhận diện. Q8 nhỏ hơn bản thường khoảng 45%,
Q5 khoảng 60%. Không có bảo đảm tốc độ hoặc độ chính xác chỉ từ các con số này.
Faster-Whisper trước đó đã dùng `compute_type=int8`: không nên coi đây là lần đầu
ứng dụng dùng lượng tử hóa, hoặc so sánh tốc độ bằng kích thước hai định dạng khác nhau.

Nguồn model: https://huggingface.co/ggerganov/whisper.cpp/tree/main
Nguồn engine: https://github.com/ggml-org/whisper.cpp

Dockerfile pin source whisper.cpp v1.8.4 vào commit
`9386f239401074690479731c1e41683fbbeac557`. Model tải từ revision
`5359861c739e955e79d9a303bcbc70fb988958b1`, kiểm tra SHA-256 theo từng biến thể.
Không tải bản `.en` vì sản phẩm dùng tiếng Việt. Model không nằm trong Git.

## Kiến trúc

1. Trình duyệt vẫn thu tự động, gửi WAV hoặc WebM qua API có đăng nhập.
2. FastAPI đưa tác vụ nhận diện vào threadpool, không chặn event loop.
3. PyAV chuyển âm thanh thành WAV mono, 16 kHz, PCM16, tối đa 30 giây/đoạn.
4. Gửi tới dịch vụ nội bộ `http://whisper-cpp:8080/inference`.
5. whisper-server giữ model trong RAM giữa các yêu cầu; 2 luồng CPU, 1 processor,
   beam size 3, không temperature fallback, không dùng context âm thanh trước.
6. Văn bản được trả về luồng hội thoại hiện có để Rasa/LLM xử lý.

Container C++ chạy bằng user không phải root và không publish port ra Internet.
DB/API key không gửi sang dịch vụ này. Model được nạp trước khi dịch vụ health báo OK.
Giữ nguyên Whisper đa ngôn ngữ; lượng tử hóa không đồng nghĩa model chuyên tiếng Việt.

API trả thêm `engine`, `model`, `elapsed_ms`. Nút ⓘ của phụ đề người dùng hiển thị
các trường này cùng nhãn và cách gán nhãn. Thời gian đo gồm đổi định dạng/gọi engine,
không gồm thời gian người dùng đang nói, upload, Rasa, LLM hoặc đọc giọng.

Ứng dụng hiện dùng một Uvicorn worker, chỉ cho một yêu cầu nhận diện tại một thời điểm.
Yêu cầu mới khi bận trả HTTP 429 thay vì chờ hàng đợi dài; client báo nói lại.
Đây là giới hạn phù hợp bản thử nghiệm VPS nhỏ, chưa giải quyết nhiều cuộc gọi đồng thời.
Tác vụ C++ có thể còn chạy sau khi client hết timeout; timeout không hủy inference bên đó.

## Khởi động và triển khai

```bash
docker compose up -d --build scam-arena
```

Lệnh tự build và chạy thêm dependency `whisper-cpp`. Lần đầu cần tải công cụ C++,
biên dịch engine và tải model ~82 MB. Những lần sau Docker dùng cache.
Build dùng hai job, tạo nhiều biến thể CPU để image không phụ thuộc CPU của máy build.
Không nên lấy thời gian build làm thời gian nhận diện.

GitHub Actions đã được cập nhật để build cả `whisper-cpp` trước khi đồng bộ source.
Nếu `.env` VPS chưa có các biến mới thì Compose dùng mặc định Q8, không cần chép đè `.env`.

```bash
docker compose ps
```

```bash
docker compose logs --tail=40 whisper-cpp
```

Log nạp model phải có `base` và `q8_0` (hoặc `q5_1` nếu chọn Q5).

## Thử Q5_1

Thêm hoặc sửa trong `.env` (giữ nguyên API key):

```dotenv
STT_PROVIDER=whisper_cpp
WHISPER_CPP_MODEL=base-q5_1
```

Sau đó build/recreate cả dependency lẫn app để thông tin model trên phụ đề đồng bộ:

```bash
docker compose up -d --build scam-arena
```

Muốn quay lại Q8, đổi thành `WHISPER_CPP_MODEL=base-q8_0` và chạy lại lệnh trên.
Không phải mọi tensor đều đổi đúng 5 hoặc 8 bit; đây là định dạng lượng tử GGML.

## Quay về Faster-Whisper

Trong `.env` đặt:

```dotenv
STT_PROVIDER=faster_whisper
WHISPER_MODEL=base
```

```bash
docker compose up -d --no-build --no-deps scam-arena
```

Chuyển engine tường minh, không tự chạy hai model khi timeout. Sidecar C++ vẫn
được Compose giữ như dependency; không tiết kiệm toàn bộ RAM của sidecar khi đổi provider.
Lệnh `--no-deps` dùng khi DB/Rasa hiện có vẫn đang chạy, cho phép đổi engine kể cả
khi sidecar C++ chưa healthy.
Ngoài Docker, cần đặt `WHISPER_CPP_URL` đúng máy chủ whisper.cpp, hoặc chọn engine cũ.

## Đánh giá cần làm với người dùng thật

- Cùng bộ âm thanh và transcript chuẩn; có giọng vùng miền, câu ngắn, phủ định,
  OTP/chuyển tiền, micro điện thoại và tiếng nền.
- So sánh Q8, Q5 và Faster-Whisper INT8: WER/CER, lỗi làm đổi ý định, độ trễ trung vị/P95,
  CPU/RAM, số lượt bị từ chối vì bận.
- Tách thời gian cắt câu/đổi định dạng/nhận diện/LLM/TTS; giữ mẫu người nói riêng khi chọn cấu hình.
- Không dùng kết quả đọc bằng Piper để tuyên bố độ chính xác hội thoại thật.

Lần thay đổi này chưa tích hợp `vad-web` vào trình duyệt. Bộ cắt câu hiện có vẫn
được giữ để đo riêng tác động của engine và lượng tử hóa.

## Thử luồng nhận diện trong Docker local

Đã thử ba đoạn **do Piper đọc**, không phải giọng người chơi. Q8 nạp đúng model
`base`, `ftype=7`, giữ model trong RAM và trả JSON tiếng Việt. Kết quả vẫn có lỗi:

| Câu tổng hợp | whisper.cpp Q8 | Faster-Whisper INT8 cũ |
| --- | --- | --- |
| Alo. | Chúng ta sẽ đi lên vậy? | Sinh câu quảng bá kênh không liên quan |
| Tôi sẽ tự gọi tổng đài để kiểm tra. | Tôi sẽ tưởng họ tổng đại đời kiểm tra. | Tôi sẽ từ họ tổng đây để kiểm tra. |
| Tôi không chuyển tiền cho người lạ. | tôi không chuyển tiền trong người lá. | Tôi không chuyển tiền trong người lạc. |

Hai đoạn dài hơn được tổng hợp chỉ khoảng 1–2 giây. Đây là kiểm tra tích hợp,
không đại diện cách nói thật và không dùng để tuyên bố WER hay tốc độ được cải thiện.
Độ trễ local ghi nhận khoảng 1,4–1,7 giây cho Q8; engine cũ khoảng 0,7–0,8 giây
ở hai lượt đã nạp model, lượt đầu khoảng 4,4 giây gồm khởi tạo. Chưa có căn cứ
khẳng định Q8 nhanh hơn engine cũ. Không dùng số này làm dự báo cho VPS.
