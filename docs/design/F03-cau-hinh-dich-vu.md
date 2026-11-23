# F03 – Cấu hình dịch vụ bên ngoài: ghi chú thiết kế

Ghi chú này viết trong lúc làm F03, làm nguyên liệu cho chương 3 (thiết kế).
F03 dựng lớp gọi dịch vụ AI mà mọi chức năng sau dùng chung (trò chuyện, lộ trình,
kho tài liệu, tìm kiếm web), cùng các trang để chủ nhóm cấu hình lớp đó cho nhóm
của mình. Cột lưu cấu hình nằm ở bảng `groups` trong `docs/design/co-so-du-lieu.md`.

Liên quan đặc tả: UC3.2 – Cấu hình dịch vụ bên ngoài (khai báo nhà cung cấp, kiểm
tra kết nối, chọn mô hình cho từng dịch vụ).

## 1. Vị trí trong kiến trúc

```text
Trình duyệt (chủ nhóm)
   │  Cài đặt > Mô hình và dịch vụ
   ▼
Ứng dụng web
   ├─ Trang: Nhà cung cấp, Mô hình ngôn ngữ, Mô hình cho việc nền,
   │         Mô hình embedding, Tìm kiếm
   └─ Kho trạng thái cài đặt: bản đang sửa trên màn hình, lưu từng mục
   ▼
Backend
   ├─ Router cấu hình mô hình (/api/settings): đọc, lưu từng mục,
   │  kiểm tra kết nối, đăng nhập ChatGPT
   ├─ Dịch vụ danh mục của nhóm: đọc, ghi groups.model_catalog,
   │  giữ bản đã giải mã trong bộ nhớ theo nhóm
   ├─ Bộ chạy kiểm tra: gọi thử từng dịch vụ, báo tiến trình theo thời gian thực
   ├─ Đăng nhập ChatGPT của nhóm: phiên lưu ở groups.codex_session
   └─ Lớp gọi dịch vụ AI: mô hình ngôn ngữ, embedding, tìm kiếm web, ChatGPT
        ▲
        └─ các chức năng sau (F04, F07, F08, …) chỉ gọi lớp này
   ▼
PostgreSQL: bảng groups
```

- Các chức năng khác không đọc cấu hình trực tiếp. Chúng gọi lớp gọi dịch vụ AI,
  lớp này lấy nhà cung cấp và mô hình đang dùng từ danh mục của nhóm có tài khoản
  đang đăng nhập.
- Chủ nhóm và người học trong nhóm dùng chung một danh mục. Nhóm khác không thấy.
- Chỉ chủ nhóm vào được các trang này. Người học gọi tới router thì bị từ chối
  (403), trừ đường đọc cài đặt giao diện của F01.

## 2. Thành phần

| Thành phần | Tầng | Làm gì |
|---|---|---|
| Router cấu hình mô hình | API | Trả danh mục (khóa đã che), lưu một thay đổi, kiểm tra nhà cung cấp, lấy danh sách mô hình, chạy kiểm tra, đăng nhập ChatGPT |
| Dịch vụ danh mục mô hình | Dịch vụ | Chuẩn hóa danh mục; chép thông tin đăng nhập từ nhà cung cấp xuống các cấu hình dùng nó |
| Danh mục của nhóm | Dịch vụ | Đọc, ghi `groups.model_catalog`; giữ bản đã giải mã trong bộ nhớ theo nhóm; làm mới khi `catalog_revision` đổi |
| Sửa từng mục | Dịch vụ | Áp một thay đổi lên danh mục đang dùng: thêm, sửa, xóa nhà cung cấp hoặc mô hình, đặt mặc định, chọn mô hình cho việc nền |
| Mã hóa | Dịch vụ | Mã hóa từng khóa API và phiên ChatGPT bằng `ENCRYPTION_KEY` trước khi ghi |
| Che và khôi phục khóa | Dịch vụ | Khóa gửi ra trình duyệt thành `***`; khi `***` quay về thì lấy lại khóa đã lưu theo mã |
| Kiểm tra nhà cung cấp | Dịch vụ | Gọi thử địa chỉ và khóa đang nhập; lấy danh sách mô hình nhà cung cấp có |
| Bộ chạy kiểm tra | Dịch vụ | Mỗi lần kiểm tra là một lượt chạy riêng: gửi một yêu cầu thật tới mô hình, báo từng bước qua luồng sự kiện, hủy được |
| Đăng nhập ChatGPT (Codex) | Dịch vụ | Mỗi nhóm một lượt đăng nhập OAuth: giữ và làm mới phiên, lấy danh sách mô hình, đặt mức suy luận |
| Chọn mô hình cho việc nền | Dịch vụ | Mỗi việc nền (đặt tên cuộc trò chuyện, gợi ý câu hỏi, …) theo mô hình chung hoặc được chọn riêng |
| Lớp gọi dịch vụ AI | Dịch vụ | Trình khách cho mô hình ngôn ngữ, embedding và tìm kiếm web, mỗi nhóm một bộ; nhiều khóa thì xoay vòng, khóa bị giới hạn tần suất thì tạm nghỉ; thử lại khi nhà cung cấp lỗi |
| Trang cài đặt mô hình | Web | Năm trang trong nhóm "Mô hình và dịch vụ"; mỗi nhà cung cấp, mỗi mô hình có nút Lưu và Hoàn tác thay đổi |

## 3. Dữ liệu

Cấu hình của nhóm nằm ở ba cột của bảng `groups`:

| Cột | Nội dung |
|---|---|
| `model_catalog` | Danh mục mô hình; khóa API và header đã mã hóa từng giá trị |
| `catalog_revision` | Tăng mỗi lần danh mục được ghi |
| `codex_session` | Phiên ChatGPT, mã hóa nguyên khối |

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

Phiên ChatGPT là một tài liệu gồm ba phần: thế hệ (tăng mỗi lần đăng nhập, làm
mới, đăng xuất), thông tin đăng nhập (mã truy cập, mã làm mới) và bộ nhớ đệm danh
sách mô hình.

Tham số gọi mô hình (nhiệt độ, độ dài trả lời) vẫn nằm trong tệp
`data/user/settings/agents.yaml`, tạo mặc định lần đầu khởi động.

## 4. Giao tiếp

Mọi đường dưới đây nằm dưới `/api/settings` và chỉ chủ nhóm gọi được, trừ khi ghi
khác. Mỗi đường làm việc trên danh mục của nhóm có tài khoản đang gọi.

| Đường API | Vào | Ra |
|---|---|---|
| `GET /` | | chủ nhóm: danh mục (khóa đã che), danh sách loại nhà cung cấp, danh sách việc nền; người học: chỉ cài đặt giao diện |
| `POST /apply/registry` | một thay đổi: thêm/sửa/xóa nhà cung cấp hoặc mô hình, đặt mặc định, chọn mô hình cho một việc nền | danh mục sau khi lưu (khóa đã che) |
| `POST /test-provider` | loại, địa chỉ, khóa (có thể là `***`) | kết nối được hay không, lỗi nếu có |
| `POST /fetch-models` | như trên | danh sách mô hình nhà cung cấp có |
| `POST /model-capabilities` | loại nhà cung cấp, mã mô hình | độ dài ngữ cảnh, khả năng đã biết |
| `POST /tests/{service}/start` | dịch vụ cần kiểm tra, danh mục trên màn hình (có thể chưa lưu) | mã lượt chạy |
| `GET /tests/{service}/{run_id}/events` | | luồng sự kiện (SSE): từng bước, kết quả |
| `POST /tests/{service}/{run_id}/cancel` | | dừng lượt chạy |
| `POST /providers/openai-codex/oauth/start` | | địa chỉ đăng nhập ChatGPT |
| `GET /providers/openai-codex/oauth/status` | | đang chờ, đã đăng nhập hay lỗi |
| `POST /providers/openai-codex/oauth/complete` | địa chỉ quay về (dán tay) | trạng thái đăng nhập |
| `POST /providers/openai-codex/oauth/cancel`, `/logout` | | trạng thái mới |
| `POST /providers/openai-codex/models/refresh` | | danh sách mô hình ChatGPT |
| `POST /providers/openai-codex/models/reasoning-effort` | mã mô hình, mức suy luận | danh mục mới |
| `GET /api/auth/openai-codex/callback` | mã và `state` do ChatGPT gửi về; công khai | trang báo đã đăng nhập |

## 5. Luồng chính

Khai báo nhà cung cấp và chọn mô hình:

1. Chủ nhóm mở trang Nhà cung cấp, thêm nhà cung cấp, nhập địa chỉ và khóa.
2. Bấm kiểm tra kết nối: web gửi những gì đang nhập tới `test-provider`; backend
   gọi thử và báo kết quả. Khóa chưa đổi được gửi dưới dạng `***` và backend tự
   lấy lại khóa đã lưu.
3. Bấm Lưu: web gửi nhà cung cấp đó tới `apply/registry`. Backend áp thay đổi lên
   danh mục đang dùng, mã hóa khóa, ghi `groups.model_catalog`, tăng
   `catalog_revision` và cập nhật bản trong bộ nhớ.
4. Ở trang Mô hình ngôn ngữ (hoặc embedding, tìm kiếm), chủ nhóm thêm mô hình từ
   một nhà cung cấp đã lưu, chọn mã trong danh sách lấy về hoặc tự nhập, rồi Lưu.
   Đặt làm mặc định, xóa và chọn mô hình cho việc nền thì lưu ngay khi bấm.
5. Chưa lưu thì mục đó hiện "Có thay đổi chưa lưu"; Hoàn tác thay đổi đưa mục về
   bản đã lưu. Rời trang khi còn mục chưa lưu thì web hỏi lại.
6. Nếu danh mục thật sự thay đổi, backend bỏ trình khách mô hình ngôn ngữ và
   embedding của nhóm đó; lời gọi AI tiếp theo của nhóm dùng cấu hình mới.

Dùng danh mục khi gọi AI:

1. Mỗi yêu cầu đã đăng nhập, lớp kiểm tra quyền đọc tài khoản rồi so
   `catalog_revision` của nhóm với bản trong bộ nhớ.
2. Khác nhau (nghĩa là một tiến trình backend khác vừa lưu) thì đọc lại danh mục,
   giải mã và bỏ trình khách cũ của nhóm.
3. Lớp gọi dịch vụ AI lấy cấu hình và trình khách của nhóm có tài khoản đang gọi.

Kiểm tra mô hình:

1. Chủ nhóm bấm chạy thử một mô hình; web gọi `tests/{service}/start` kèm danh mục
   đang trên màn hình, nên kiểm tra được cả thay đổi chưa lưu.
2. Backend tạo lượt chạy, gửi một yêu cầu thật tới mô hình đang chọn.
3. Web nghe luồng sự kiện và hiện từng bước: địa chỉ gọi tới, câu trả lời mẫu,
   độ dài ngữ cảnh dò được, lỗi nếu có.
4. Độ dài ngữ cảnh hay số chiều dò được thì chủ nhóm bấm dùng giá trị đó rồi Lưu.

Đăng nhập ChatGPT:

1. Chủ nhóm bấm đăng nhập trên thẻ ChatGPT; backend mở một cổng chờ trên máy
   (1455, bận thì 1457) và trả địa chỉ đăng nhập của OpenAI.
2. Chủ nhóm đăng nhập trên trình duyệt; OpenAI chuyển về địa chỉ chờ đó.
3. Backend đổi mã nhận được lấy phiên, mã hóa và lưu vào `groups.codex_session`,
   thêm nhà cung cấp ChatGPT và các mô hình vào danh mục của nhóm.
4. Nếu trình duyệt không tới được cổng chờ (chạy trên máy khác), chủ nhóm dán địa
   chỉ trên thanh địa chỉ vào ô trên thẻ; backend chỉ nhận đúng địa chỉ của lần
   đăng nhập đang chờ.
5. Phiên tự làm mới khi còn dưới 5 phút. Đăng xuất thì thu hồi phiên, xóa phiên
   khỏi nhóm và gỡ nhà cung cấp ChatGPT khỏi danh mục; đang có câu trả lời chạy
   bằng ChatGPT thì không cho đăng xuất.

## 6. Quyết định thiết kế

- **Mỗi nhóm một danh mục.** Chủ nhóm khai báo nhà cung cấp và mô hình một lần cho
  cả nhóm. Người học dùng danh mục của nhóm mình; nhóm khác không đọc được.
- **Lưu ngay, không bản nháp.** Mỗi thao tác chỉ đổi một mục (một nhà cung cấp,
  một mô hình, một lựa chọn), lưu là có hiệu lực. Bản đang sửa chỉ nằm trên màn
  hình cho tới khi bấm Lưu. Cách này bỏ được cả một lớp trạng thái (lưu nháp, áp
  dụng một phần, bỏ nháp) mà vẫn cho sửa xong mới lưu.
- **Danh mục trong cơ sở dữ liệu, bản giải mã trong bộ nhớ.** Danh mục được đọc ở
  hầu hết lời gọi AI nên không thể mỗi lần đều hỏi cơ sở dữ liệu. Backend giữ bản
  đã giải mã theo nhóm, chỉ đọc lại khi `catalog_revision` đổi; phép so sánh là
  một lần đọc số nguyên theo khóa chính ở mỗi yêu cầu.
- **Khóa được mã hóa từng giá trị.** Chỉ khóa API và header bị mã hóa; phần còn lại
  của danh mục vẫn đọc được để dễ kiểm tra. `ENCRYPTION_KEY` phải giữ cố định:
  đổi khóa thì khóa đã lưu không giải mã được.
- **Khóa không bao giờ ra khỏi máy chủ.** Mọi trường giống khóa bị che bằng `***`.
  Khi trình duyệt gửi lại `***`, backend lấy khóa thật đã lưu theo mã của nhà cung
  cấp, kể cả khi kiểm tra kết nối.
- **Trình khách AI riêng từng nhóm.** Cấu hình đã phân giải và trình khách mô hình
  ngôn ngữ, embedding được giữ theo nhóm, để nhóm này không bao giờ chạy bằng mô
  hình hay khóa của nhóm khác. Vì cùng lý do, khóa API không được chép vào biến môi
  trường của tiến trình.
- **Chỉ tạo lại trình khách khi danh mục đổi thật.** Lưu lại cùng cấu hình không
  cắt ngang câu trả lời đang chạy.
- **Nhà cung cấp tách khỏi mô hình.** Địa chỉ và khóa nhập một lần ở nhà cung
  cấp; backend chép xuống mọi cấu hình dùng nhà cung cấp đó, nên lớp gọi dịch vụ
  AI vẫn đọc từng cấu hình độc lập. Mô hình chỉ gắn được vào nhà cung cấp đã lưu.
- **Mỗi nhóm một lượt đăng nhập ChatGPT.** Phiên mã hóa nguyên khối trong
  `groups.codex_session`. Mỗi lần ghi chỉ thành công nếu phiên trong cơ sở dữ liệu
  vẫn là bản vừa đọc, nên một lần làm mới đến muộn không ghi đè lần đăng nhập mới
  hay làm sống lại phiên đã đăng xuất.
- **Mô hình cho việc nền riêng.** Đặt tên cuộc trò chuyện, gợi ý câu hỏi, đặt tên
  lộ trình là các lời gọi ngắn và thường xuyên, nên có thể dùng mô hình nhỏ và rẻ
  hơn. Chưa chọn gì thì các việc này dùng mô hình đang trả lời.
- **Kiểm tra bằng lời gọi thật, báo dần.** Lời gọi tới mô hình có thể mất vài giây;
  luồng sự kiện cho chủ nhóm thấy đang ở bước nào và hủy được.
- **Không ghi nhật ký từng lời gọi.** Mỗi lượt trò chuyện vẫn mang tổng số token
  và chi phí của nó; không có bảng ghi riêng từng lời gọi mô hình.

## 7. Giao diện

| Màn | Nội dung |
|---|---|
| Nhà cung cấp | Danh sách bên trái, chi tiết bên phải: tên, loại, địa chỉ, khóa; phần nâng cao gồm định dạng API, header, proxy; kiểm tra kết nối; thẻ đăng nhập ChatGPT; Lưu, Hoàn tác thay đổi, Xóa |
| Mô hình ngôn ngữ | Danh sách mô hình và chi tiết: nhà cung cấp, mã mô hình (chọn từ danh sách lấy về hoặc tự nhập), độ dài ngữ cảnh, khả năng, mức suy luận; chạy thử; Lưu, Hoàn tác thay đổi, đặt mặc định, Xóa |
| Mô hình cho việc nền | Một mô hình chung, hoặc chọn riêng từng việc; hai nhóm Trò chuyện và Lộ trình; chọn là lưu |
| Mô hình embedding | Như mô hình ngôn ngữ, thêm số chiều |
| Tìm kiếm | Cấu hình công cụ tìm kiếm web từ nhà cung cấp đã lưu; chạy thử; Lưu |
| Rời trang | Còn mục chưa lưu thì hỏi tiếp tục sửa hay rời đi không lưu |
