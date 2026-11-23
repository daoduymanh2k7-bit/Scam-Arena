> Historical benchmark. The optional C++ engine and comparison command have been removed; use this report only as past measurement evidence.

# Lựa chọn engine nhận diện: Faster-Whisper INT8

Ngày so sánh: 20/11/2026. Quyết định hiện tại: **Faster-Whisper base INT8** làm mặc định.
Đây là quyết định tạm thời dựa trên cấu hình đã thử, không khẳng định một repo luôn tốt hơn repo kia.

## Phương pháp

- Chạy local Docker trên cùng máy, cả hai engine dùng 2 luồng CPU.
- 6 câu tiếng Việt, tạo đúng một bản âm thanh cho mỗi câu bằng Piper preset `quang-huy`.
- Chuẩn hóa cùng âm thanh thành WAV mono 16 kHz PCM16, dùng lại cho cả hai engine.
- Nạp và chạy thử mỗi engine trước khi bắt đầu đo; không tính tải/nạp model.
- Chạy mỗi câu hai lần trên mỗi engine, đảo thứ tự engine xen kẽ.
- Như vậy có **6 câu khác nhau**, 12 lượt đo/engine; không phải 12 người nói hay 12 câu độc lập.
- Faster-Whisper: `base`, CPU INT8, 2 threads, cấu hình decoder mặc định của thư viện (beam 5).
- whisper.cpp: `base-q8_0`, 2 threads, beam 3, best-of 1, không temperature fallback.
- So sánh hai cấu hình thực tế, không tách riêng ảnh hưởng của engine, decoder và lượng tử hóa.
- WER tính Levenshtein trên token tách theo khoảng trắng, lowercase/NFC, bỏ dấu câu nhưng giữ dấu tiếng Việt.

## Kết quả

| Chỉ số | Faster-Whisper INT8 | whisper.cpp Q8_0 |
| --- | ---: | ---: |
| Trung vị nhận diện | 1,080 giây | 2,110 giây |
| Lượt chậm nhất | 1,236 giây | 2,284 giây |
| Lỗi token / tổng token chuẩn | 16 / 116 | 21 / 116 |
| WER trên bộ tổng hợp này | 13,8% | 18,1% |

Trên bộ này, Faster-Whisper vừa nhanh hơn vừa có ít lỗi token hơn. Vì vậy chọn lại
Faster-Whisper INT8 cho ứng dụng, thay vì giữ C++ chỉ vì đã tích hợp nó.

## Giới hạn

- Âm thanh **tổng hợp**, chỉ một giọng, mẫu ít và có lặp. Không suy ra chất lượng
  giọng Bắc/Trung/Nam, tiếng nền, micro thật hoặc khả năng phục vụ đồng thời.
- Các lượt lặp không phải các quan sát độc lập; đây là phép thử chọn cấu hình ban đầu.
- Không phải số đo trên VPS. Không dùng để cam kết người dùng sẽ được giảm một nửa độ trễ.
- Chưa đo cùng decoder/beam, model FP16, Q5, nhiều model hoặc tách riêng HTTP overhead.
- Cả hai vẫn có thể nghe sai từ quan trọng: ví dụ `chưa` thành `chơi`.
  Việc chọn engine không có nghĩa phần nhận diện đã hoàn thiện.
- Chưa thử hai engine ở chế độ streaming. Chất lượng phụ đề còn phụ thuộc VAD và micro.

## Chạy lại

Cần có voice Piper `vi_VN-csa-voice-piper-v3-medium.onnx` và file cấu hình đi kèm
trong `voices/` để tái tạo đúng preset `quang-huy` của phép thử này.

Khởi động riêng dịch vụ đối chứng (không đổi provider của web):

```bash
docker compose up -d --build --wait whisper-cpp
```

```bash
docker compose exec -T scam-arena python backend/tools/compare_speech_engines.py
```

Script in từng câu chuẩn, kết quả, thời gian và thống kê. Đừng chạy trên VPS đang
phục vụ nhiều cuộc gọi vì phép thử cạnh tranh CPU với người dùng thật.

Sau khi thử, nếu ứng dụng dùng Faster-Whisper:

```bash
docker compose stop whisper-cpp
```

Để quyết định chắc hơn cần bộ bản thu của người nói thật có đồng ý chia sẻ,
transcript chuẩn được duyệt, tách người nói khi chọn cấu hình và đánh giá cuối,
đo WER/CER, lỗi đổi ý định, độ trễ trung vị/P95 và CPU/RAM trên VPS.
