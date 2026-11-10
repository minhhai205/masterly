# Chương 2. Phân tích và đặc tả yêu cầu

Chương này trình bày bài toán và các yêu cầu đối với Masterly. Phần đầu khảo sát bài toán và các giải pháp đã có; phần tiếp theo xác định tác nhân và đặc tả các ca sử dụng; cuối chương là các yêu cầu phi chức năng.

## 2.1. Khảo sát bài toán

### 2.1.1. Bối cảnh và động lực

Ngày nay nhiều người tự học bằng AI: đưa tài liệu lên, đặt câu hỏi và nhận lời giải thích ngay. Cách học này còn hai hạn chế:

- Tưởng đã hiểu nhưng chưa nắm vững: đọc lời giải thích trôi chảy dễ tạo cảm giác đã hiểu, trong khi người học chưa tự trả lời câu hỏi nào.
- Học xong rồi quên: không có ai nhắc ôn lại đúng lúc.

Hai hạn chế này rõ nhất với những nội dung chưa có lộ trình soạn sẵn, như một môn chuyên ngành theo giáo trình riêng, một cuốn sách hay tài liệu nơi làm việc.

Vì vậy, người tự học cần một hệ thống không chỉ trả lời câu hỏi mà còn dẫn dắt, kiểm tra và nhắc ôn tập.

### 2.1.2. Phát biểu bài toán

Xây dựng một ứng dụng web giúp người học tự học có hệ thống theo mục tiêu của mình:

1. Từ mục tiêu của người học, kèm tài liệu nếu có, hệ thống lập lộ trình gồm các điểm kiến thức.
2. Với mỗi điểm kiến thức, AI giảng giải và đặt câu hỏi.
3. Hệ thống đánh giá câu trả lời và chỉ cho học tiếp khi người học đã nắm vững.
4. Các điểm đã học được xếp lịch ôn tập.

Yêu cầu cốt lõi: việc xét người học đã nắm vững hay chưa phải dựa trên kết quả làm bài thực tế, theo quy tắc nhất quán, không dựa vào cảm nhận của người học hay nhận xét của AI.

### 2.1.3. Các giải pháp tiêu biểu đã có

- NotebookLM (Google): hỏi đáp trên tài liệu tải lên, có dẫn nguồn; tạo tóm tắt, thẻ ghi nhớ và câu hỏi từ tài liệu.
- ChatGPT Study Mode (OpenAI), tương tự Guided Learning của Gemini và Learning mode của Claude: AI hướng dẫn từng bước, hỏi gợi mở thay vì đưa đáp án ngay.
- Khan Academy và Khanmigo: học đến khi thành thạo trên các bài học soạn sẵn, có gia sư AI dẫn dắt.
- Anki (mã nguồn mở): người học tự soạn thẻ ghi nhớ, mỗi thẻ có lịch ôn riêng.

**Bảng 2.1. So sánh các giải pháp tiêu biểu**

| Giải pháp | Học trên tài liệu, nội dung riêng | Lộ trình theo mục tiêu | Xét nắm vững | Ôn tập theo lịch |
|---|---|---|---|---|
| NotebookLM | Có | Không | Không | Không |
| ChatGPT Study Mode | Có | Không | Không | Không |
| Khan Academy và Khanmigo | Không | Soạn sẵn | Có | Không |
| Anki | Có | Không | Không | Có |
| Masterly | Có | Có | Có | Có |

Nhận xét:

- NotebookLM và ChatGPT Study Mode cho học trên tài liệu, nội dung riêng, nhưng không có lộ trình, không xét nắm vững và không nhắc ôn tập.
- Khan Academy xét nắm vững chặt chẽ, nhưng chỉ trên các bài học soạn sẵn.
- Anki xếp lịch ôn tốt, nhưng người học phải tự soạn thẻ và không có lộ trình hay người giảng.

Chưa có giải pháp nào có đủ cả bốn yếu tố trên.

### 2.1.4. Giải pháp đề xuất

Masterly là một vòng học khép kín: nêu mục tiêu, kèm tài liệu nếu có → lập lộ trình → học từng điểm kiến thức → kiểm tra nắm vững → ôn tập theo lịch.

Điểm khác biệt cốt lõi là tách hai vai trò:

- AI: lập lộ trình, giảng giải, đặt câu hỏi.
- Hệ thống: đánh giá câu trả lời, xét người học đã nắm vững hay chưa, chọn bước học tiếp theo và cho biết lý do.

Một lần trả lời đúng chưa đủ để coi là nắm vững; các điểm đã nắm vững vẫn được kiểm tra lại qua các lần ôn.

Ngoài vòng học chính, người học còn có thể:

- hỏi đáp tự do với AI trên tài liệu của mình;
- ghi chép trong lúc học;
- được hệ thống ghi nhớ thông tin qua các buổi học để AI hỗ trợ phù hợp hơn.

Mọi nội dung được tổ chức theo không gian học, ví dụ mỗi môn học một không gian.

Quy trình học theo lộ trình:

1. Nêu mục tiêu: người học mô tả điều muốn học và chọn tài liệu làm nguồn.
2. Chốt dàn ý: gia sư AI hỏi về kiến thức đã có, mức muốn đạt, thời gian có, rồi đề xuất dàn ý; người học chỉnh và chốt.
3. Học và làm bài: gia sư giảng giải rồi ra câu hỏi; hệ thống đánh giá và cập nhật mức nắm vững.
4. Qua điểm kiến thức: đã nắm vững thì chuyển sang điểm tiếp theo, chưa thì luyện tiếp.
5. Ôn tập: điểm đến hạn ôn được ưu tiên trước nội dung mới.

![Hình 2.1. Biểu đồ hoạt động của quy trình học theo lộ trình](images/hoat-dong-hoc-theo-lo-trinh.png)

**Hình 2.1. Biểu đồ hoạt động của quy trình học theo lộ trình**

### 2.1.5. Phạm vi hệ thống

- Ứng dụng web, giao diện tiếng Việt và tiếng Anh.
- Mỗi người dùng có tài khoản và dữ liệu riêng; tài khoản do quản trị viên cấp, không có tự đăng ký.
- Việc sinh câu trả lời, xử lý tài liệu và tìm kiếm web dùng dịch vụ AI bên ngoài; hệ thống không tự huấn luyện mô hình.

## 2.2. Yêu cầu chức năng

### 2.2.1. Xác định các tác nhân

Hệ thống có hai tác nhân, đều là người dùng có tài khoản do quản trị viên cấp. Các dịch vụ bên ngoài mà hệ thống kết nối tới không phải tác nhân.

**Bảng 2.2. Danh sách các tác nhân của hệ thống**

| STT | Tác nhân | Mô tả |
|---|---|---|
| 1 | Người học | Người dùng các chức năng học tập trên dữ liệu của riêng mình. |
| 2 | Quản trị viên | Người học có thêm quyền quản lý tài khoản và cấu hình các dịch vụ bên ngoài dùng chung. Hệ thống có một quản trị viên. |

### 2.2.2. Biểu đồ ca sử dụng tổng quát

Các ca sử dụng được chia thành ba nhóm (Hình 2.2):

- Học theo lộ trình: phần lõi của hệ thống.
- Hỗ trợ học tập: các chức năng phục vụ việc học, gồm hỏi đáp, tài liệu, ghi chép, bộ nhớ và không gian học.
- Quản trị hệ thống: phần nền để hệ thống hoạt động.

Người học dùng các ca sử dụng của hai nhóm đầu. Quản trị viên có toàn bộ ca sử dụng của người học, thêm cấp và thu hồi tài khoản, cấu hình dịch vụ bên ngoài.

![Hình 2.2. Biểu đồ ca sử dụng tổng quát của hệ thống Masterly](images/ca-su-dung-tong-quat.png)

**Hình 2.2. Biểu đồ ca sử dụng tổng quát của hệ thống Masterly**

**Bảng 2.3. Danh sách các ca sử dụng của hệ thống**

| Nhóm | Mã | Tên ca sử dụng | Tác nhân |
|---|---|---|---|
| 1. Học theo lộ trình | UC1.1 | Lập lộ trình | Người học |
| | UC1.2 | Học một điểm kiến thức | Người học |
| | UC1.3 | Ôn tập theo lịch | Người học |
| | UC1.4 | Theo dõi tiến độ lộ trình | Người học |
| 2. Hỗ trợ học tập | UC2.1 | Trò chuyện với AI | Người học |
| | UC2.2 | Tải lên và sắp xếp tài liệu học | Người học |
| | UC2.3 | Ghi chép trong lúc học | Người học |
| | UC2.4 | Điều chỉnh bộ nhớ người học | Người học |
| | UC2.5 | Tổ chức không gian học | Người học |
| 3. Quản trị hệ thống | UC3.1 | Cấp và thu hồi tài khoản | Quản trị viên |
| | UC3.2 | Cấu hình dịch vụ bên ngoài | Quản trị viên |
