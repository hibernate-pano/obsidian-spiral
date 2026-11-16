# 变更记录

## 0.1.0 — 2026-11-16

首个版本。

**自动采集**
- 新增 `serve.py`：静态服务 + 按需重采，替代 `python3 -m http.server`。
  页面沿用原有 60 秒轮询，服务在 `ttl` 过期时当场跑采集，不再需要手动重采。
- `collect.py` 拆出 `collect_all()` / `write_payload()` 供服务复用。
- 浏览历史日期只在缺文件时补采一次，翻日期不卡秒。

**修复**
- `first_prompt` 只取每个项目第一条 user 消息，首条若是系统噪声就永久丢失。
  改为按时间戳记录最早的真人指令。
- PI 的 prompt key 在 `cwd` 读到前后会分裂，导致首条指令丢失。
- 补全系统噪声前缀（`Base directory for this skill`、`[Workflow harness` 等）。

**其他**
- 去掉硬编码的家目录用户名，`humanize()` 改为按 `HOME` 推导。
- `humanize()` 里一段永远不生效的中文库名反查循环已删除。
- 采集产物 `data*.json` 不入库（含本地路径与会话内容）。
