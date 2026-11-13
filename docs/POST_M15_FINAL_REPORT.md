# Báo cáo nghiên cứu FilingScope sau M15

## 1. Giới hạn của M1–M15

Bản gốc `1218f9002fca5c0c11774a97be5e7b1e21428719` đã có LangGraph,
Evidence Ledger, truy xuất Dense, Company Facts và xác minh nguồn. Trên
M13, bản gốc chỉ trả lời đúng và đủ nguồn 1/21 câu ở chế độ định tuyến B5
và 3/21 ở chế độ ép nghiên cứu B4. Cả hai từ chối đúng 3/3 câu đối chứng.
Các lỗi tập trung ở nối cột bảng với kỳ báo cáo, chuyển dữ liệu SEC và
chọn nguồn. [M13](ABLATION_STUDY.md), [đánh giá gốc](POST_M15_FAILURE_ANALYSIS.md).

## 2. Q1 — Quy nguyên nhân

Đã truy vết 38/38 lượt thất bại. Lỗi đầu tiên nằm ở gán kỳ theo tiêu đề
bảng 27 lượt, đọc ô 2, chuẩn hóa XBRL 2, định tuyến nguồn 3, thiếu ứng
viên 2 và xếp hạng ngoài ngưỡng 2. Can thiệp A–G chỉ hoạt động trong
đánh giá. Đưa thẳng trang PDF đúng vào vẫn không khôi phục câu trả lời
trong 35 lượt thử C. Chỉ bỏ cổng sufficiency trong thí nghiệm E phục hồi
7 câu sau khi qua bộ xác minh gốc. Phân tích này ưu tiên chuẩn hóa bảng,
nguồn SEC theo kỳ và chọn đường truy xuất phù hợp. [Q1](POST_M15_FAILURE_ANALYSIS.md).

## 3. Q2 — Chuẩn hóa tài chính

Kỳ tài khóa có định danh cho năm, quý riêng, YTD và thời điểm. Bộ đọc
pypdf xác định hàng, cột, đơn vị và dấu. SEC giữ CIK, accession, concept,
tiền tệ, kỳ và bản sửa đổi. Trích xuất đúng 57/57 ô PDF đã gán nhãn so với
19/57 trước đó, và 9/9 quan sát SEC. Trên 22 cặp ô/trang M13 đã biết
vị trí, kết quả tăng từ 13/22 lên 19/22. [Q2](POST_M15_FINANCIAL_NORMALIZATION.md).

## 4. Q3 — Định tuyến theo khả năng của nguồn

Câu tra cứu đi qua SEC trực tiếp, trang báo cáo đã chuẩn hóa hoặc tìm
kiếm văn bản có giới hạn theo yêu cầu. Đối chứng validation đạt 9/9 với
9 lượt gọi công cụ, so với 8/9 và 20 lượt khi ép nghiên cứu. M13 tăng
từ 3/21 lên 14/21 so với B5 sau Q2. [Q3](POST_M15_SOURCE_ROUTING.md).

## 5. Q4 — Rủi ro và độ bao phủ

Chính sách yêu cầu đúng đơn vị phát hành, kỳ, chỉ tiêu, dạng nguồn và
mức hỗ trợ của từng phát biểu. Bộ validation 10 câu chuyển từ 0/4 lên
4/4 câu đúng đủ nguồn, từ chối đúng 6/6. Độ bao phủ 4/10, rủi ro công bố
thiếu nguồn 0/4, cận trên Wilson 95% là 48,99%. M13 tăng từ 14/21 lên
21/21, giữ 3/3 lượt từ chối đúng. [Q4](POST_M15_EVIDENCE_POLICY.md).

## 6. Q5 — Thí nghiệm truy xuất

Trong 28 cấu hình, xếp hạng theo ô báo cáo trong 100 ứng viên Dense
được chọn. Validation ép nghiên cứu tăng từ 10/17 lên 17/17. Với định
tuyến bình thường, tăng từ 14/17 lên 17/17, chênh lệch ghép cặp 17,6
điểm phần trăm (bootstrap theo nhóm doanh nghiệp 6,3–28,6). M12 Recall@10
giữ 56,3%. Graph PageRank đạt 83,3% Recall@10 trên M12 và 14/17 câu đúng
trên bộ validation khác. DBSF đạt 65,3% và 1/17 trên hai phép đo tương ứng.
[Q5](POST_M15_RETRIEVAL_UTILITY.md).

## 7. Q6 — Viết và xác minh câu trả lời

Writer và verifier dùng cùng các dữ kiện đã duyệt và thứ tự nguồn.
Phép tính Decimal được kiểm tra trước khi viết và khi xác minh. Bốn câu
3M tăng kết quả từ 26/30 lên 30/30, chênh lệch 13,3 điểm (CI theo nhóm
0–40 điểm). Cổng sửa tối đa một lượt. Với bản nháp mô phỏng trên sáu câu
có đáp án, bản P5 chưa qua cổng đạt 3/6, P5 qua cổng đạt 0/6, writer xác
định đạt 6/6, writer mô phỏng mới đạt 4/6 với 0/4 lượt công bố thiếu nguồn.
Chất lượng của provider trực tiếp vẫn chưa được đo. [Q6](POST_M15_GROUNDED_WRITER.md).

## 8. Q7 — SEC trực tiếp, RAG thích ứng và LangGraph

| Bộ câu hỏi | SEC trực tiếp | RAG thích ứng | LangGraph định tuyến | LangGraph ép nghiên cứu |
| --- | ---: | ---: | ---: | ---: |
| M13, câu có đáp án | 11/21 | 21/21 | 21/21 | 21/21 |
| Q3, câu tra cứu có đáp án | 12/14 | 14/14 | 14/14 | 14/14 |
| Q7, so sánh doanh nghiệp | 0/12 | 12/12 | 12/12 | 12/12 |
| Q7, công bố ngành | 0/2 | 2/2 | 2/2 | 2/2 |

Trong 10 lượt mô phỏng lỗi cố định của một hồ sơ, LangGraph giữ đủ các
mục từ doanh nghiệp còn truy cập được 10/10 so với 5/10 ở RAG thích ứng.
Hai luồng cùng từ chối kết luận đầy đủ. Cả hai phục hồi đúng 10/10 khi
lỗi chỉ xảy ra một lần. CI bootstrap ghép cặp cho giữ nguồn là [+50, +50]
điểm theo thiết kế hai hướng của năm cặp. Kiểm định dấu hai phía p=0,0625.
Kết quả giới hạn ở cách mô phỏng lỗi này. [Q7](POST_M15_SPECIALIST_ARCHITECTURES.md).

## 9. Q8 — An toàn, truy vết và CI

Chín ca chèn lệnh qua văn bản hồ sơ chạy với Groq mô phỏng. Các bản nháp
tấn công đều bị chặn khi phát hành. Writer chỉ gửi các phát biểu đã
chuẩn hóa và khung công bố ngành đã duyệt. Transport chỉ có hợp đồng tạo
văn bản. Nhật ký JSON dùng ID băm và mã lỗi định danh, kèm thời gian và
usage theo công đoạn. Kiểm thử cục bộ đạt 399 ca, 0 lỗi và 3 bỏ qua vì
thiếu fixture HTML. CI kiểm tra cú pháp, dependency, tập tin tracked,
suite offline và chỉ số xác minh fixture. Lần chạy đầu thất bại ở kiểm
tra phạm vi `runner.temp`. Sau khi sửa tại `7817975`, GitHub Actions đạt
398 ca, bỏ qua 4 ca do thiếu dữ liệu cục bộ và đạt 100% trên fixture xác
minh. Nhật ký quét tệp tracked báo 0 vấn đề.
[Lần chạy GitHub Actions](https://github.com/NamTV2712/filingscope/actions/runs/43339910663).

API loopback xác nhận đúng doanh thu quý 3M, hai tỷ lệ tăng trưởng của
Apple và Microsoft, và từ chối đúng yêu cầu bản sửa đổi của PayPal.
Ba lượt này tạo 23 stage trace hợp lệ, có trích dẫn cho hai câu trả lời
và không chứa câu hỏi gốc trong nhật ký.

## 10. So sánh benchmark cuối

| Bộ đánh giá | Mốc so sánh | Kết quả |
| --- | --- | --- |
| M13 lịch sử, 24 câu | B5 đóng băng → Q8 định tuyến | 1/21 → 21/21 đúng đủ nguồn. Sai khi từ chối 20/21 → 0/21. Từ chối đúng 3/3. |
| P5 FinanceBench lịch sử, 150 câu | A4 và A5 gốc | A4 công bố 3/150. A5 từ chối 150/150. Chưa chạy phép đối chiếu hosted mới. |
| Q5/Q6 development, 13 câu | Q5 tự nhiên → Q8 | 9/13 → 13/13. Bốn câu phục hồi đều thuộc 3M. |
| Q5/Q6 validation, 20 câu | Q5 tự nhiên → Q8 | 17/17 giữ nguyên. Từ chối đúng 3/3, công bố thiếu nguồn 0/17. |
| Q7 provisional, 12 câu so sánh | Thích ứng → LangGraph định tuyến | 12/12 ở cả hai. Mỗi nhóm development 4/4 và validation 8/8. |
| Final độc lập | Bộ câu hỏi do reviewer giữ kín | Chưa có dữ liệu đủ điều kiện để chạy. [Quy trình bàn giao và chấm offline](POST_M15_EVALUATION_PROTOCOL.md#reviewer-handoff-and-execution). |

M13 ghép cặp có 20 cải thiện và 0 suy giảm, chênh lệch +95,24 điểm phần
trăm với bootstrap mô tả 88–100 điểm trên chín nhóm theo nhãn doanh nghiệp
(10.000 lượt, seed `20261112`). Dữ liệu M13 đã dùng trong phát triển.
Điểm P5 là số liệu lịch sử trên một tập khác. Không suy ra mức rủi ro 2–5%
trong triển khai từ các mẫu này.

## 11. Lỗi theo lớp câu hỏi

| Lớp M13 | Lỗi B5 gốc | Lỗi Q8 | Nguyên nhân đã xử lý |
| --- | ---: | ---: | --- |
| Tra cứu đơn | 9/9 | 0/9 | Chọn SEC hoặc báo cáo theo dạng nguồn, kỳ và tính sẵn có |
| Nguồn nhiễu khó | 5/5 | 0/5 | Ghép ô đúng kỳ, đúng phạm vi và đúng nguồn |
| Phép tính | 3/3 | 0/3 | Khôi phục đủ toán hạng và kiểm tra Decimal |
| Một hồ sơ | 1/1 | 0/1 | Tra cứu đúng phạm vi và kỳ báo cáo |
| Nhiều hồ sơ | 1/1 | 0/1 | Gộp nguồn theo yêu cầu |
| Nhiều doanh nghiệp, nhiều bước | 1/1 | 0/1 | Tách doanh nghiệp và xác minh hai chuỗi toán hạng |
| Bản sửa đổi | 0/1 | 0/1 | Duy trì chính sách chọn accession |
| Mâu thuẫn, chèn lệnh, vô nghiệm | 0/3 | 0/3 | Duy trì từ chối đúng |

Hai câu công bố ngành kiểm tra một khung ngữ nghĩa hẹp. Phạm vi định
tính mở, hòa giải ngữ cảnh thay đổi và doanh nghiệp ngoài catalog vẫn
cần bộ đối chứng lớn hơn.

## 12. Độ trễ, bộ nhớ và chi phí

| Phép đo | Giá trị |
| --- | --- |
| M13 B5 → Q8 p50/p95 | 82,55/219,88 → 15,26/149,12 ms |
| M13 B5 → Q8 công cụ trung bình | 1,08 → 1,33 |
| M13 B5 → Q8 token bằng chứng trung bình | 3.167 → 249 |
| Q8 tra cứu p50/p95 | 12,81/15,54 ms, 1 công cụ trung bình |
| Q8 replay 33 câu p50/p95 | 20,51/134,25 ms, 38 công cụ và 14 lượt embedding |
| Q8 bộ nhớ đỉnh | Khoảng 2,01 GB cho so sánh kiến trúc và 2,02 GB cho replay truy xuất |
| Q8 các replay mặc định | 0 lượt LLM, 0 token sinh câu trả lời, 0 USD provider |
| P5 lịch sử | 461 lượt thử provider, 460 phản hồi, chi phí mô hình 0,354987 USD |

Trên Q7 sạch, RAG thích ứng dùng 1,58 công cụ trung bình, LangGraph định
tuyến dùng 5,50. Thử I/O giả lập có lợi khi ba worker chạy đồng thời.
Thử Dense thật có khóa chung cho embedding và serial nhanh hơn trong
lần đo Q7. Thời gian trên là đo warm trên CPU, ngoài chi phí tải mô hình.

## 13. Phương pháp được giữ, thử nghiệm và loại bỏ

Giữ Dense làm đối chứng, statement rank có phạm vi, SEC trước khi phù hợp,
Evidence Ledger, writer xác định và kiểm tra nguyên tử. Giữ phạm vi worker
độc lập với tối đa một lượt thử lại truy xuất. Graph PageRank và ColBERT
còn ở nhánh thí nghiệm đánh giá. Trì hoãn Qdrant multivector làm mặc định.
Loại RRF, DBSF, parent expansion đại trà và cross-encoder khỏi cấu hình
mặc định theo kết quả Q5. LangGraph vẫn là bộ điều phối hiện hành.

## 14. Rủi ro chất lượng còn lại

Bộ mẫu đã biết không đo được tổng quát hóa trên doanh nghiệp, kỳ, tiền tệ
và biểu mẫu mới. Dữ liệu SEC có giới hạn về concept, revision và dữ liệu
theo phân khúc. Nghiên cứu phức tạp còn trùng nhiều ứng viên. Phản hồi
provider thật, nhiều loại công bố định tính và rủi ro ngoài tập chèn lệnh
đã thử đều chưa được định lượng.

## 15. Lệnh tái lập và artifact

```powershell
python -m scripts.run_offline_checks
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
uv run --offline --with psutil==7.2.2 python -m scripts.run_specialist_architectures `
  --faults --output data/financebench/ablation_runs/replay-architectures.json `
  --manifest data/financebench/ablation_runs/replay-architectures-manifest.json
```

[Hướng dẫn tái lập](POST_M15_REPRODUCIBILITY.md) có lệnh cho dữ liệu,
SEC, replay writer, kiểm tra manifest và provider tùy chọn. Các bản đo
cuối trong `data/financebench/ablation_runs` gồm kiến trúc, truy xuất tự
nhiên và writer. Tệp dữ liệu thô, trọng số và kết quả chi tiết là local.

| Tệp kết quả hoặc manifest | SHA-256 |
| --- | --- |
| `post-m15-baseline.json` | `a483ea98f6a3d98dc0104abaf3583decfc6b9015a3daa2ab356e8694e8ffd12a` |
| `q8-final-architectures.json` | `9d7f29e80cb158441338398a3a90b96f162ea1ca38a6d9b0cd2a224f1bb3ce53` |
| `q8-final-architectures-manifest.json` | `4fc1ded7e80079021e1235eadcf0e0f2de9d580025cd86df19959757639ae75f` |
| `q8-final-natural-runtime.json` | `f424cbc6228eed5178d6c9c25bccd18af047ad643be2c5ddfd1cb09913040c98` |
| `q8-final-writer-summary.json` | `d11089c5d1f8e17db904258598d4d9f3f6a22742fb889ed1e4dfdb38c966e595` |
| `q8-final-writer-manifest.json` | `85430544b9d44a116d00f8bbdbeb853064fb7e684d795a0ca3e9e962a824d2fa` |
| `q8-loopback-stage-smoke.json` | `339fb845e909288d951bc9c9ebbf39805fae63a40bc8dbf6a38a2842143a01b3` |

## 16. Kiến trúc mã hiện tại

Yêu cầu đi qua bộ nhận diện doanh nghiệp, chỉ tiêu và kỳ, sau đó chọn
FAST, RESEARCH hoặc UNSUPPORTED. FAST gọi SEC hoặc truy xuất bảng/văn
bản theo khả năng nguồn. RESEARCH dùng supervisor và các worker đã có.
Ledger liên kết nguồn, ô, slot và phép tính. Chính sách bằng chứng xác
định đủ dữ kiện. Writer tạo bản nháp từ dữ kiện duyệt. Bộ xác minh nguyên
tử quyết định công bố, công bố một phần hoặc từ chối. API loopback trả
kết quả và trích dẫn, trace tùy chọn ghi theo công đoạn.

## 17. Câu hỏi nghiên cứu tiếp theo

Đo độ chính xác và rủi ro theo cỡ mẫu đủ lớn trên tập độc lập do reviewer
giữ kín. Kiểm tra một bộ điều khiển thích ứng tiếp tục xử lý nguồn còn
sống sau lỗi khi đủ ngân sách. Đo khả năng dùng lại ứng viên liên quan
đến nhiều slot cùng hồ sơ để giảm truy xuất trùng. Mở rộng tập đánh giá
công bố định tính và bản sửa đổi có đủ nguồn.

## 18. Công việc website để sau

Thiết kế và mở rộng website thuộc giai đoạn riêng. So sánh Git từ baseline
Post-M15 cho thấy ba tệp giao diện hiện có giữ nguyên. Phần chạy website
được xác minh qua API loopback. GitHub Actions chỉ chạy kiểm thử backend.
