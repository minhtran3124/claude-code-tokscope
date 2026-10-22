# Research: quản lý Managed Agents (`ant` CLI) trong tokscope

Ngày: 2026-10-22. Kết luận: **khả thi**, rủi ro thấp nếu gọi `ant` qua subprocess và chỉ mở hành động ghi ở level `full`.

## 1. `ant` là gì (đã kiểm tra trên máy này)

- `ant` 2.1.0 tại `~/.local/bin/ant`: "CLI for the Claude Developer Platform" (Go, sinh từ API spec).
- Đã đăng nhập: `ant auth status` → profile `default`, kiểu `user_oauth`, org KT Inc. Credentials ở `~/.config/anthropic/credentials/default.json`, `ant` tự refresh token.
- Các resource liên quan (`ant <resource> --help`):

| Resource | Lệnh | Endpoint (thấy qua `--debug`) |
| --- | --- | --- |
| `beta:agents` | create, retrieve, update, list, archive | `GET /v1/agents?beta=true` |
| `beta:sessions` | create, retrieve, update, list, delete, archive, connect | `GET /v1/sessions?beta=true` |
| `beta:deployments` | create, retrieve, update, list, archive, **pause, unpause, run** | `GET /v1/deployments`, `POST /v1/deployments/{id}/pause` |
| `beta:deployment-runs` | retrieve, list | |

- Header beta: `anthropic-beta: managed-agents-2026-04-01` (CLI tự gửi).
- Output máy đọc được: `--format json` (hoặc `jsonl`), lọc bằng `--transform` (GJSON). List hỗ trợ `--limit` (≤100), `--page`, `--max-items`, filter `--agent-id`, `--status`, `--created-at-gte/lte`.

## 2. Dữ liệu thật trả về (list, chỉ đọc)

- **Agents**: `id`, `name`, `model {id, effort, speed}`, `mcp_servers`, `skills`, `tools`, `system` (system prompt đầy đủ), `metadata`.
- **Deployments**: `id`, `name`, `status` (`paused`…), `paused_reason {type: manual}`, `schedule {type: cron, expression, timezone, last_run_at, upcoming_runs_at[]}`, `agent {id, version}`, `budget {max_list_cost}`, `environment_id`, `initial_events` (prompt khởi động), `resources` (memory stores), `vault_ids`.
  Hiện có 2 deployment, cả hai `paused` (manual): "Travel-pi brief" (`45 7 * * 1-5`) và "Daily brief" (`32 7 * * 1-5`), múi giờ Asia/Ho_Chi_Minh.
- **Sessions**: `id`, `status` (`idle`…), `title`, `agent`, `deployment_id`, `stats {active_seconds, duration_seconds}` và **`usage`**: `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation {ephemeral_5m, ephemeral_1h}`, `server_tool_use`, `list_cost {amount, currency}`.

Điểm đáng chú ý: session có token và chi phí theo từng lần chạy, nên tokscope có thể đo tiền theo deployment/agent đúng với mục đích hiện tại của nó (token theo skill/subagent/phase).

## 3. Cách tích hợp

### A. Gọi `ant` qua subprocess (khuyến nghị)

```python
subprocess.run(["ant", "beta:deployments", "list", "--format", "json"], capture_output=True, text=True, timeout=30)
subprocess.run(["ant", "beta:deployments", "pause", "--deployment-id", dep_id, "--format", "json"], ...)
```

- Ưu: tokscope không bao giờ đọc hay giữ token; OAuth refresh, workspace, profile, AWS/GCP đều do `ant` lo; giữ đúng quy tắc chỉ dùng stdlib; đã có mẫu tương tự (`skills.py` gọi `git`).
- Nhược: cần `ant` đã cài và đã login (thiếu thì hiện thông báo hướng dẫn `ant auth login`); mỗi lần gọi tốn ~0.3–1 s; output phụ thuộc phiên bản CLI beta.

### B. Gọi HTTP trực tiếp bằng `urllib`

- Cần access token: hoặc đọc file credentials, hoặc `ant auth print-credentials`. Như vậy tokscope phải giữ một bí mật, việc mà hiện giờ nó không làm. Không nên chọn, trừ khi A quá chậm.

## 4. UI đề xuất (trang mới "Agents" trong dashboard)

1. **Deployments**: tên, trạng thái (chip running/paused + lý do), cron và giờ địa phương, lần chạy kế tiếp, budget, tổng cost của các session thuộc deployment. Nút **Pause / Unpause**, và tùy chọn **Run now**.
2. **Sessions**: list theo thời gian, lọc theo agent/deployment; cột status, thời lượng, input/output/cache tokens, `list_cost`.
3. **Agents**: tên, model/effort, MCP servers, skills; system prompt thu gọn.
4. Lấy dữ liệu: cache trong bộ nhớ 30–60 s và có nút Refresh. Không đưa vào vòng poll 2 s của `api/version` (mỗi lần poll là một lần gọi mạng ra ngoài).

Route khớp với handler hiện có:
- `GET api/ant/deployments|sessions|agents` → subprocess list, trả JSON đã rút gọn.
- `POST ant/deployments/pause|unpause|run` → đi qua `do_POST` hiện có, vốn đã chặn sai Host, sai Origin, thiếu `X-Tokscope-Token` và body không phải JSON.

## 5. Rủi ro và cách xử lý

| Rủi ro | Xử lý |
| --- | --- |
| Hành động ghi lên cloud (pause/unpause/run) bị kích hoạt từ trang lạ (CSRF) | Dùng guard sẵn có của `do_POST`; chỉ cho phép ở `level == "full"` (giống `api/optimize`) |
| Chèn tham số vào lệnh | argv dạng list, không dùng `shell=True`; kiểm tra id bằng `^depl_[A-Za-z0-9]{10,40}$` trước khi gọi |
| `run` tốn tiền | Hộp xác nhận ngay trong trang (không dùng `confirm()`), hiện budget trước khi chạy |
| Lộ dữ liệu nhạy cảm (system prompt, `initial_events`, tên vault) ở level redacted | Ở level khác `full` chỉ hiện số liệu, ẩn văn bản |
| API beta đổi field | Đọc field bằng `.get()`, ghi phiên bản `ant` tối thiểu đã thử (2.1.0); có test parse từ fixture JSON |
| Chưa cài `ant` hoặc token hết hạn | Bắt `FileNotFoundError` và exit code ≠ 0, hiện stderr đã rút gọn kèm gợi ý `ant auth login` |
| Org có nhiều workspace | Bản đầu dùng profile/workspace mặc định của `ant`; thêm chọn workspace sau |

## 6. Phạm vi và ước lượng

- **PR 1 (chỉ đọc)**: module `tokscope/ant.py` (wrapper subprocess, rút gọn JSON, cache), trang Agents gồm 3 bảng, test với fixture. Khoảng 1 PR cỡ vừa.
- **PR 2 (hành động)**: pause/unpause (và run nếu muốn) qua `do_POST`, xác nhận trong trang, test cho guard và validate id.
- **Tùy chọn PR 3**: ingest `usage` của session vào SQLite của tokscope để Overview gộp chi phí Managed Agents với Claude Code.
- Ngoài phạm vi: `sessions connect` (terminal tương tác), tạo hoặc sửa agent/deployment (đã có `ant apply`).

## 7. Câu hỏi cho owner

1. Có cần **Run now** không, hay chỉ pause/unpause?
2. Có ingest chi phí session vào DB (PR 3) để xem chung với Claude Code không?
3. Trang này chỉ dành cho level `full` hay cũng hiện số liệu ở các level redacted?
