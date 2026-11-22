# F01 – Đăng nhập: ghi chú thiết kế

Ghi chú này viết trong lúc làm F01, làm nguyên liệu cho chương 3 (thiết kế). Vì
F01 là phần nền, ghi chú kiêm luôn kiến trúc tổng thể và cách tổ chức dữ liệu mà
mọi chức năng sau dùng chung.

Liên quan đặc tả: mục 2.3 (yêu cầu phi chức năng: tài khoản do quản trị viên cấp,
phiên có thời hạn, dữ liệu mỗi người tách riêng, giao diện sáng/tối, hai ngôn ngữ).

## 1. Kiến trúc tổng thể

```text
Trình duyệt
   │  chỉ nói chuyện với địa chỉ của ứng dụng web
   ▼
Ứng dụng web (Next.js)
   ├─ Trang: đăng nhập, trang chủ, hồ sơ, cài đặt
   └─ Proxy: chặn trang khi chưa có phiên; chuyển /api, /ws, /files sang backend
   ▼
Backend (FastAPI)
   ├─ Lớp API: các router, mỗi router một nhóm chức năng
   ├─ Lớp kiểm tra quyền: xác định người dùng của từng yêu cầu
   ├─ Lớp dịch vụ: tài khoản, cấu hình, cài đặt giao diện
   └─ Lớp lưu trữ: tệp JSON và thư mục dữ liệu theo từng tài khoản
```

- Trình duyệt không biết địa chỉ backend; proxy của ứng dụng web chuyển tiếp.
  Nhờ vậy cookie phiên luôn cùng nguồn với trang và không phải mở CORS rộng.
- Mọi đường API trừ đăng nhập, đăng xuất, kiểm tra phiên và đọc cài đặt giao diện
  đều đi qua lớp kiểm tra quyền.

## 2. Thành phần

| Thành phần | Tầng | Làm gì |
|---|---|---|
| Khởi động ứng dụng | Backend | Tạo cấu hình mặc định lần đầu, bật log, gắn router, đồng bộ quản trị viên khi khởi động |
| Router đăng nhập | API | Đăng nhập, đăng xuất, kiểm tra phiên, hồ sơ và ảnh đại diện của chính mình |
| Lớp kiểm tra quyền | API | `require_auth` (bắt buộc có phiên), `require_admin` (chỉ quản trị viên), `optional_auth` (có phiên thì nhận ra người dùng), bản dùng cho WebSocket |
| Dịch vụ tài khoản | Dịch vụ | Băm và kiểm tra mật khẩu (bcrypt), tạo và giải mã phiên (JWT), quản lý kho tài khoản |
| Ngữ cảnh người dùng | Dịch vụ | Lưu người dùng của yêu cầu hiện tại; mọi đường dẫn dữ liệu đọc từ đây |
| Dịch vụ đường dẫn | Lưu trữ | Trả về thư mục dữ liệu của người dùng hiện tại (và của không gian học hiện tại) |
| Router và dịch vụ cài đặt giao diện | API, dịch vụ | Đọc và lưu theme, ngôn ngữ giao diện của từng tài khoản |
| Khung web | Web | Bố cục, thanh bên, theme áp dụng trước khi trang hiện, đa ngôn ngữ |

## 3. Dữ liệu

```text
data/
├─ system/                 dữ liệu của cả hệ thống
│  └─ auth/
│     ├─ users.json        kho tài khoản
│     ├─ auth_secret       khóa ký phiên, tự sinh lần đầu
│     └─ avatars/          ảnh đại diện, đặt tên theo mã tài khoản
├─ user/                   dữ liệu của quản trị viên
│  ├─ settings/            cấu hình hệ thống: system.json, auth.json, …
│  │                       và interface.json của quản trị viên
│  ├─ workspace/           nội dung học của không gian mặc định
│  └─ logs/
└─ users/<mã tài khoản>/   dữ liệu của từng người học, cùng cấu trúc với data/user
```

Tài khoản (một bản ghi trong `users.json`):

| Trường | Ý nghĩa |
|---|---|
| id | Mã cố định dạng `u_…`; thư mục dữ liệu đặt theo mã này nên đổi tên đăng nhập không làm mất dữ liệu |
| username | Tên đăng nhập, là khóa của bản ghi |
| hash | Mật khẩu đã băm bằng bcrypt |
| role | `admin` hoặc `user` (người học) |
| created_at | Ngày tham gia |
| disabled | Khóa tài khoản |
| avatar | Rỗng, `icon:<biểu tượng>:<màu>` hoặc `img:<phiên bản>` |

Cài đặt giao diện (`interface.json` của từng tài khoản): `theme` (`light`, `dark`),
`language` (`vi`, `en`).

## 4. Giao tiếp

| Đường API | Quyền | Vào | Ra |
|---|---|---|---|
| `GET /api/auth/status` | công khai | cookie phiên (nếu có) | đã đăng nhập chưa, mã, tên, vai trò, ảnh |
| `POST /api/auth/login` | công khai | tên đăng nhập, mật khẩu | đặt cookie phiên; mã, tên, vai trò |
| `POST /api/auth/logout` | công khai | | xóa cookie phiên |
| `GET /api/auth/profile` | có phiên | | thông tin tài khoản của chính mình |
| `PUT /api/auth/profile` | có phiên | biểu tượng ảnh đại diện | ảnh đại diện mới |
| `PUT, DELETE /api/auth/profile/avatar` | có phiên | tệp ảnh PNG, JPEG, WebP, tối đa 1 MB | ảnh đại diện mới |
| `GET /api/auth/avatar/{mã}` | có phiên | | tệp ảnh |
| `GET /api/settings/ui` | công khai | cookie phiên (nếu có) | theme, ngôn ngữ của tài khoản (hoặc mặc định) |
| `PUT /api/settings/ui` | có phiên | theme và/hoặc ngôn ngữ | cài đặt sau khi lưu |

## 5. Luồng chính

Đăng nhập:

1. Người dùng mở một trang bất kỳ. Proxy thấy chưa có cookie phiên hợp lệ thì
   chuyển sang trang đăng nhập, kèm địa chỉ trang muốn vào.
2. Người dùng nhập tên đăng nhập và mật khẩu; web gửi tới `POST /api/auth/login`.
3. Dịch vụ tài khoản tìm bản ghi, kiểm tra mật khẩu bằng bcrypt.
4. Đúng thì tạo phiên JWT (có hạn) và trả về trong cookie httpOnly; sai thì trả
   lỗi 401 và trang hiện thông báo.
5. Web quay lại trang người dùng muốn vào.

Mỗi yêu cầu sau khi đăng nhập:

1. Lớp kiểm tra quyền đọc cookie (hoặc header Bearer), giải mã và kiểm tra phiên.
2. Gắn người dùng vào ngữ cảnh của yêu cầu.
3. Dịch vụ đường dẫn đọc ngữ cảnh đó để trả về đúng thư mục dữ liệu của tài khoản.

## 6. Quyết định thiết kế

- **Không có tự đăng ký.** Quản trị viên khai báo trong `auth.json` (tên đăng nhập
  và mật khẩu đã băm). Khi khởi động, tài khoản này được ghi vào kho tài khoản để
  có mã, ngày tham gia và ảnh đại diện như mọi tài khoản khác; mật khẩu luôn lấy
  theo `auth.json`, đổi ở đó thì lần khởi động sau có hiệu lực.
- **Phiên là JWT trong cookie httpOnly**: JavaScript không đọc được cookie; backend
  không phải lưu phiên; hết hạn theo `token_expire_hours`. Proxy của web chỉ xem
  hạn của phiên để chuyển hướng sớm, còn chữ ký luôn do backend kiểm tra.
- **Lớp kiểm tra quyền là hàm bất đồng bộ.** Nếu chạy đồng bộ, FastAPI chạy nó ở
  luồng khác và người dùng gắn vào ngữ cảnh bị mất trước khi tới endpoint; dữ liệu
  sẽ rơi vào nhầm thư mục.
- **Thư mục dữ liệu đặt theo mã tài khoản**, không theo tên đăng nhập.
- **Không gian học mặc định từ đầu.** Mọi nội dung đã lưu theo không gian học (mặc
  định); khi có chức năng tạo và chuyển không gian (F05) thì không phải sửa dữ liệu.
- **Ảnh đại diện kiểm tra theo nội dung tệp**, không tin tên tệp hay kiểu tệp do
  trình duyệt gửi; không nhận SVG.
- **Cài đặt giao diện lưu ở hai nơi**: trình duyệt (để trang hiện đúng theme ngay
  từ đầu, không nhấp nháy) và tài khoản (để mở trên máy khác vẫn giữ). Lựa chọn
  trong trình duyệt được ưu tiên.

## 7. Giao diện

| Màn | Nội dung |
|---|---|
| Đăng nhập | Tên đăng nhập, mật khẩu, nút đăng nhập; dòng "Tài khoản do quản trị viên cấp" |
| Khung chung | Thanh bên: trang chủ; cuối thanh là cài đặt, hồ sơ, đăng xuất; thu gọn được; trên điện thoại là ngăn kéo |
| Trang chủ | Lời chào; chỗ này sau dành cho trò chuyện (F04) và lộ trình (F08) |
| Hồ sơ | Tên, vai trò, ngày tham gia; đổi ảnh đại diện bằng ảnh tải lên hoặc biểu tượng và màu; đăng xuất |
| Cài đặt | Chọn theme sáng/tối (có ảnh xem trước); chọn ngôn ngữ giao diện |
