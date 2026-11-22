# F03 – Cấu hình dịch vụ bên ngoài: ghi chú thiết kế

Ghi chú này viết trong lúc làm F03, làm nguyên liệu cho chương 3 (thiết kế).
F03 dựng lớp gọi dịch vụ AI mà mọi chức năng sau dùng chung (trò chuyện, lộ trình,
kho tài liệu, tìm kiếm web), cùng các trang để quản trị viên cấu hình lớp đó.

Liên quan đặc tả: UC3.2 – Cấu hình dịch vụ bên ngoài (khai báo nhà cung cấp, kiểm
tra kết nối, chọn mô hình cho từng dịch vụ).

## 1. Vị trí trong kiến trúc

```text
Trình duyệt (quản trị viên)
   │  Cài đặt > Mô hình và dịch vụ
   ▼
Ứng dụng web
   ├─ Trang: Nhà cung cấp, Mô hình ngôn ngữ, Mô hình cho việc nền,
   │         Mô hình embedding, Tìm kiếm
   └─ Kho trạng thái cài đặt: giữ bản nháp đang sửa, gửi lưu nháp / áp dụng
   ▼
Backend
   ├─ Router cấu hình mô hình (/api/settings): đọc, lưu nháp, áp dụng,
   │  kiểm tra kết nối, đăng nhập ChatGPT
   ├─ Dịch vụ danh mục mô hình: một tệp cấu hình chung cho cả hệ thống
   ├─ Dịch vụ bản nháp: thay đổi chưa áp dụng
   ├─ Bộ chạy kiểm tra: gọi thử từng dịch vụ, báo tiến trình theo thời gian thực
   └─ Lớp gọi dịch vụ AI: mô hình ngôn ngữ, embedding, tìm kiếm web, ChatGPT
        ▲
        └─ các chức năng sau (F04, F07, F08, …) chỉ gọi lớp này
```

- Các chức năng khác không đọc tệp cấu hình. Chúng gọi lớp gọi dịch vụ AI, và lớp
  này lấy nhà cung cấp, mô hình đang dùng từ danh mục.
- Chỉ quản trị viên vào được các trang này. Người học gọi tới router thì bị từ
  chối (403), trừ đường đọc cài đặt giao diện của F01.

## 2. Thành phần

| Thành phần | Tầng | Làm gì |
|---|---|---|
| Router cấu hình mô hình | API | Trả danh mục (khóa đã che), lưu và bỏ bản nháp, áp dụng toàn bộ hoặc từng phần, kiểm tra nhà cung cấp, lấy danh sách mô hình, chạy kiểm tra, đăng nhập ChatGPT |
| Dịch vụ danh mục mô hình | Dịch vụ | Đọc, chuẩn hóa và ghi danh mục; chép thông tin đăng nhập từ nhà cung cấp xuống các cấu hình dùng nó |
| Dịch vụ bản nháp | Dịch vụ | Lưu thay đổi chưa áp dụng ở tệp riêng; không phần nào khi chạy đọc tệp này |
| Che và khôi phục khóa | Dịch vụ | Khóa gửi ra trình duyệt thành `***`; khi `***` quay về thì lấy lại khóa đã lưu theo mã |
| Kiểm tra nhà cung cấp | Dịch vụ | Gọi thử địa chỉ và khóa đang nhập; lấy danh sách mô hình nhà cung cấp có |
| Bộ chạy kiểm tra | Dịch vụ | Mỗi lần kiểm tra là một lượt chạy riêng: gửi một yêu cầu thật tới mô hình, báo từng bước qua luồng sự kiện, hủy được |
| Đăng nhập ChatGPT (Codex) | Dịch vụ | Đăng nhập OAuth, giữ và làm mới phiên, lấy danh sách mô hình, đặt mức suy luận |
| Chọn mô hình cho việc nền | Dịch vụ | Mỗi việc nền (đặt tên cuộc trò chuyện, gợi ý câu hỏi, …) theo mô hình chung hoặc được chọn riêng |
| Lớp gọi dịch vụ AI | Dịch vụ | Trình khách cho mô hình ngôn ngữ, embedding và tìm kiếm web; nhiều khóa thì xoay vòng, khóa bị giới hạn tần suất thì tạm nghỉ; thử lại khi nhà cung cấp lỗi |
| Trang cài đặt mô hình | Web | Năm trang trong nhóm "Mô hình và dịch vụ"; thanh công cụ lưu nháp, bỏ, áp dụng |

## 3. Dữ liệu

```text
data/
├─ system/
│  └─ secrets/<mã quản trị viên>/   phiên đăng nhập ChatGPT, chỉ chủ tiến trình đọc được
└─ user/settings/                  cấu hình hệ thống (thư mục của quản trị viên)
   ├─ model_catalog.json           danh mục mô hình, dùng chung cho mọi tài khoản
   ├─ settings_draft.json          bản nháp chưa áp dụng (chỉ có khi đang sửa dở)
   └─ agents.yaml                  tham số gọi mô hình (nhiệt độ, độ dài trả lời),
                                   tạo mặc định lần đầu khởi động
```

Danh mục mô hình:

```text
danh mục
├─ connections[]          nhà cung cấp: tên, loại, địa chỉ, khóa, header, proxy
└─ services
   ├─ llm                 mô hình ngôn ngữ trả lời người học
   ├─ task                mô hình cho việc nền, kèm lựa chọn riêng từng việc
   ├─ embedding           mô hình xử lý tài liệu để tra cứu
   └─ search              công cụ tìm kiếm web
        mỗi dịch vụ: cấu hình đang dùng, mô hình đang dùng, danh sách cấu hình
        mỗi cấu hình: nhà cung cấp gắn vào, định dạng API, danh sách mô hình
        mỗi mô hình: tên hiển thị, mã mô hình, độ dài ngữ cảnh, khả năng,
                     số chiều (embedding)
```

Phiên ChatGPT gồm ba tệp: thông tin đăng nhập (mã truy cập, mã làm mới), trạng
thái và bộ nhớ đệm danh sách mô hình.

## 4. Giao tiếp

Mọi đường dưới đây nằm dưới `/api/settings` và chỉ quản trị viên gọi được, trừ khi
ghi khác.

| Đường API | Vào | Ra |
|---|---|---|
| `GET /` | | quản trị viên: danh mục (khóa đã che), danh sách loại nhà cung cấp, danh sách việc nền; người học: chỉ cài đặt giao diện |
| `GET, PUT, DELETE /draft` | bản nháp | bản nháp sau khi lưu (khóa đã che) hoặc rỗng |
| `POST /apply` | danh mục, hoặc không gửi gì để áp dụng bản nháp đã lưu | danh mục sau khi áp dụng; bản nháp bị xóa |
| `POST /apply/service` | tên dịch vụ, cấu hình của dịch vụ đó | danh mục mới; phần nháp của dịch vụ khác giữ nguyên |
| `POST /apply/provider` | một cấu hình nhà cung cấp | như trên |
| `POST /apply/registry` | một thay đổi nhỏ: thêm/sửa/xóa nhà cung cấp hoặc mô hình, đặt mặc định, chọn mô hình cho một việc nền | như trên |
| `POST /test-provider` | loại, địa chỉ, khóa (có thể là `***`) | kết nối được hay không, lỗi nếu có |
| `POST /fetch-models` | như trên | danh sách mô hình nhà cung cấp có |
| `POST /model-capabilities` | loại nhà cung cấp, mã mô hình | độ dài ngữ cảnh, khả năng đã biết |
| `POST /tests/{dịch vụ}/start` | dịch vụ cần kiểm tra | mã lượt chạy |
| `GET /tests/{dịch vụ}/{mã}/events` | | luồng sự kiện (SSE): từng bước, kết quả |
| `POST /tests/{dịch vụ}/{mã}/cancel` | | dừng lượt chạy |
| `POST /providers/openai-codex/oauth/start` | | địa chỉ đăng nhập ChatGPT |
| `GET /providers/openai-codex/oauth/status` | | đang chờ, đã đăng nhập hay lỗi |
| `POST /providers/openai-codex/oauth/complete` | địa chỉ quay về (dán tay) | trạng thái đăng nhập |
| `POST /providers/openai-codex/oauth/cancel`, `/logout` | | trạng thái mới |
| `POST /providers/openai-codex/models/refresh` | | danh sách mô hình ChatGPT |
| `POST /providers/openai-codex/models/reasoning-effort` | mã mô hình, mức suy luận | danh mục mới |
| `GET /api/auth/openai-codex/callback` | mã và `state` do ChatGPT gửi về; công khai | trang báo đã đăng nhập |

## 5. Luồng chính

Khai báo nhà cung cấp và chọn mô hình:

1. Quản trị viên mở trang Nhà cung cấp, thêm nhà cung cấp, nhập địa chỉ và khóa.
2. Bấm kiểm tra kết nối: web gửi những gì đang nhập tới `test-provider`; backend
   gọi thử và báo kết quả. Khóa chưa đổi được gửi dưới dạng `***` và backend tự
   lấy lại khóa đã lưu.
3. Quản trị viên lưu nhà cung cấp; backend ghi ngay nhà cung cấp đó vào danh mục
   (`apply/provider`) mà không đụng phần nháp khác.
4. Ở trang Mô hình ngôn ngữ (hoặc embedding, tìm kiếm), quản trị viên thêm mô hình
   từ nhà cung cấp đã lưu, chọn mã trong danh sách lấy về hoặc tự nhập, đặt làm
   mặc định.
5. Những sửa đổi chưa áp dụng nằm trong bản nháp. Thanh công cụ cho lưu nháp, bỏ
   nháp hoặc áp dụng. Áp dụng thì backend ghi danh mục và xóa bản nháp.
6. Nếu danh mục thật sự thay đổi, backend tạo lại trình khách mô hình ngôn ngữ và
   embedding; lời gọi AI tiếp theo dùng cấu hình mới.

Kiểm tra mô hình:

1. Quản trị viên bấm chạy thử một mô hình; web gọi `tests/{dịch vụ}/start`.
2. Backend tạo lượt chạy, gửi một yêu cầu thật tới mô hình đang chọn.
3. Web nghe luồng sự kiện và hiện từng bước: địa chỉ gọi tới, câu trả lời mẫu,
   độ dài ngữ cảnh dò được, lỗi nếu có.
4. Với embedding, số chiều đo được ghi luôn vào mô hình.

Đăng nhập ChatGPT:

1. Quản trị viên bấm đăng nhập trên thẻ ChatGPT; backend mở một cổng chờ trên máy
   (1455, bận thì 1457) và trả địa chỉ đăng nhập của OpenAI.
2. Quản trị viên đăng nhập trên trình duyệt; OpenAI chuyển về địa chỉ chờ đó.
3. Backend đổi mã nhận được lấy phiên, lưu vào thư mục bí mật của quản trị viên,
   thêm nhà cung cấp ChatGPT và các mô hình vào danh mục.
4. Nếu trình duyệt không tới được cổng chờ (chạy trên máy khác), quản trị viên dán
   địa chỉ trên thanh địa chỉ vào ô trên thẻ; backend chỉ nhận đúng địa chỉ của
   lần đăng nhập đang chờ.
5. Phiên tự làm mới khi còn dưới 5 phút. Đăng xuất thì thu hồi phiên, xóa tệp và
   gỡ nhà cung cấp ChatGPT khỏi danh mục; đang có câu trả lời chạy bằng ChatGPT thì
   không cho đăng xuất.

## 6. Quyết định thiết kế

- **Một danh mục chung.** Nhà cung cấp và mô hình do quản trị viên khai báo một
  lần, áp dụng cho mọi tài khoản. Khi người học dùng một chức năng gọi AI, hệ thống
  đọc danh mục trong thư mục của quản trị viên.
- **Đăng nhập ChatGPT cũng dùng chung.** Phiên lưu trong thư mục bí mật của quản
  trị viên; mọi tài khoản dùng phiên đó.
- **Bản nháp tách khỏi cấu hình đang chạy.** Sửa nhiều trang rồi áp dụng một lần;
  bản nháp lưu trên máy chủ nên tải lại trang hay đổi máy không mất. Lưu một nhà
  cung cấp, một mô hình hoặc một dịch vụ thì chỉ phần đó được áp dụng, phần nháp
  khác giữ nguyên.
- **Khóa không bao giờ ra khỏi máy chủ.** Mọi trường giống khóa (khóa API, mã, mật
  khẩu) bị che bằng `***`. Khi trình duyệt gửi lại `***`, backend lấy khóa thật đã
  lưu theo mã của nhà cung cấp, kể cả khi kiểm tra kết nối.
- **Nhà cung cấp tách khỏi mô hình.** Địa chỉ và khóa nhập một lần ở nhà cung
  cấp; backend chép xuống mọi cấu hình dùng nhà cung cấp đó, nên lớp gọi dịch vụ
  AI vẫn đọc từng cấu hình độc lập. Xóa nhà cung cấp thì cấu hình giữ khóa đang có
  thay vì hỏng.
- **Chỉ tạo lại trình khách khi danh mục đổi thật.** Bấm áp dụng lại cùng cấu hình
  không cắt ngang câu trả lời đang chạy của người học.
- **Mô hình cho việc nền riêng.** Đặt tên cuộc trò chuyện, gợi ý câu hỏi, đặt tên
  lộ trình là các lời gọi ngắn và thường xuyên, nên có thể dùng mô hình nhỏ và rẻ
  hơn. Chưa chọn gì thì các việc này dùng mô hình đang trả lời.
- **Kiểm tra bằng lời gọi thật, báo dần.** Lời gọi tới mô hình có thể mất vài giây;
  luồng sự kiện cho quản trị viên thấy đang ở bước nào và hủy được.
- **Mức suy luận của ChatGPT lưu ngay.** Đây là một lựa chọn trên thẻ ChatGPT, không
  phải sửa danh mục, nên không qua bản nháp.

## 7. Giao diện

| Màn | Nội dung |
|---|---|
| Nhà cung cấp | Danh sách bên trái, chi tiết bên phải: tên, loại, địa chỉ, khóa; phần nâng cao gồm định dạng API, header, proxy; kiểm tra kết nối; thẻ đăng nhập ChatGPT |
| Mô hình ngôn ngữ | Danh sách mô hình và chi tiết: nhà cung cấp, mã mô hình (chọn từ danh sách lấy về hoặc tự nhập), độ dài ngữ cảnh, khả năng, mức suy luận; đặt mặc định; chạy thử |
| Mô hình cho việc nền | Một mô hình chung, hoặc chọn riêng từng việc; hai nhóm Trò chuyện và Lộ trình |
| Mô hình embedding | Như mô hình ngôn ngữ, thêm số chiều; chạy thử ghi lại số chiều đo được |
| Tìm kiếm | Cấu hình công cụ tìm kiếm web từ nhà cung cấp đã lưu; chạy thử |
| Thanh công cụ | Báo có thay đổi chưa áp dụng; lưu nháp, bỏ, áp dụng |
