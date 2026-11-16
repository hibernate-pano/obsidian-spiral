# 螺旋日程 · AI 会话盘

把一天的 agent 会话 + 日记记录画成一条向内的螺旋。纯本地、只读、不装插件、不改 Obsidian 配置。

**v0.1.0** · 单文件 Canvas 2D，无 CDN、无依赖，只有 Python 标准库。

## 快速开始

```bash
python3 serve.py ~/你的库路径
# → http://127.0.0.1:8899/index.html
```

一条命令：起服务 + 自动采集。后台每 `ttl` 秒重采今天的数据，页面每 60 秒轮询读文件，
**不用再手动跑 collect.py**，请求也不会因为采集而变慢。

```bash
python3 serve.py <库路径> --port 8899 --ttl 60
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `vault` | 必填 | Obsidian 库路径，日记来源 |
| `--port` | 8899 | 监听端口 |
| `--ttl` | 60 | 后台重采间隔（秒） |
| `--no-warm` | — | 启动时不预热采集 |

## 它画的是什么

一条连续向内的螺旋，**6 圈 = 24 小时**（每圈 4 小时，外圈 00:00）。

| 图层 | 视觉 | 数据来源 |
|---|---|---|
| **agent 会话** | 彩色发光弧线 | Claude Code / Codex / PI 的本地日志 |
| **日记记录** | 白色小圆环 | 日记正文里的 `[HH:MM]` |
| **螺旋基线** | 深灰底槽 | — |

彩线长短 = 那段会话持续多久。相邻消息间隔超过 5 分钟算断开，
所以一整天会碎成几十个真实片段，而不是一条糊在一起的粗线。

## 支持三个 agent

| 来源 | 日志路径 | 侧栏徽章 |
|---|---|---|
| **Claude Code** | `~/.claude/projects/**/*.jsonl` | `CLAUDE` |
| **Codex** | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` | `CODEX` |
| **PI** | `~/.pi/agent/sessions/<编码cwd>/*.jsonl` | `PI` |

同一项目开多个会话文件会按 cwd 自动合并成一条。

三者 token 都取 **输出 token**（Claude `usage.output_tokens`、Codex `usage.output_tokens`、
PI `usage.output`），口径一致。PI 的 usage 字段实测完全统一，读不到就记 0 的情况只在
「那段会话没有 assistant 回复」时出现——那是真的 0，不是解析失败。

## 动态效果

1. **实时脉冲** —— 当前时刻光点呼吸 + 环形波纹
2. **弧形生长** —— 回放时线从起点长出来
3. **三层描边** —— 柔光雾 + 主体 + 白色高光芯，灯管质感
4. **悬停放大** —— 扫过弧线，那段变粗发光
5. **播放今天** —— 12 秒重演一整天
6. **日期切换** —— 左上角 `‹` `›` 翻日，「今天」跳回

## Obsidian 原生联动

| 交互 | 效果 |
|---|---|
| 点日记白环 / 待办条目 | `obsidian://open` 直接跳进当天日记 |
| 点弧线 / 侧栏来源 | 会话详情卡：开场指令 + 每段时间，点某段回放直接跳到那一段 |
| 「嵌到 Obsidian」按钮 | 复制 iframe 片段，粘进任意笔记即可在 Obsidian 里内嵌实时螺旋盘 |
| 键盘 | `空格` 播放/停止，`←` `→` 切日期，`Esc` 关卡片 |

嵌入原理：Obsidian 笔记原生渲染 iframe。前提是 `serve.py` 在跑。

## 只采某一天（存档）

`serve.py` 是常驻服务；要单独采某天或批量补历史，直接用 `collect.py`：

```bash
python3 collect.py <库路径>                 # 今天
python3 collect.py <库路径> 2026-11-13      # 指定日期
```

输出两个文件：
- `data-YYYY-MM-DD.json` —— 按日期留档
- `data.json` —— 始终指向最近一次采集

## 实测数据

2026-11-12（最忙的一天）：
```
22 个来源 / 44 段会话
6.3h 有记录 · 304 万 token
```

2026-11-13：
```
Claude 8 + Codex 7 / 46 段
4.2h 有记录 · 170 万 token（Claude 133 万 + Codex 37 万）
```

2026-10-08（只有 PI 的一天）：
```
PI 1 个来源 / 17 段 · 37.8 万 token
```

## 已知限制（诚实说）

1. **日历层没接** —— `collect.py` 会尝试 `alma calendar`，没权限就记 `no-permission`
   并跳过；`index.html` 也还没画日历条。
2. **iframe 内嵌要服务活着** —— Obsidian 里的嵌入页面依赖端口，
   电脑重启后要重新 `python3 serve.py <库路径>`。
3. **百分比低是真实的** —— 记录本来就稀疏。想让图更满只能多记，不是把刻度改好看。
4. **只读** —— 不写回你的库，不改 Obsidian 配置。
5. **采集产物不入库** —— `data*.json` 含本地绝对路径和会话内容，已 gitignore。

## 文件

```
spiral/
├── serve.py      服务 + 自动采集（日常入口）
├── collect.py    采集器（可单独采某一天）
├── index.html    可视化（单文件，离线可用）
├── LICENSE       MIT
└── CHANGELOG.md
```
