#!/usr/bin/env python3
"""把 Obsidian 日记 + agent 会话日志 → 一份给螺旋盘用的 JSON。

真实数据来源：
- agent 时段/令牌：~/.claude/projects/**/*.jsonl（实测可用）
- 待办/计划：Obsidian 日记里的 `## AI 代办` 和 `- [ ]` 行
- 日历：可选，调用本机的 `alma calendar`（没装或没权限就跳过，不编）

输出给 index.html 用，落在本目录的 data-YYYY-MM-DD.json / data.json。
"""
import json
import glob
import os
import re
import subprocess
import sys
import datetime
import urllib.parse
from pathlib import Path

HOME = Path.home()
GAP = 300  # 相邻消息超过 5 分钟算断

# 这些开头的"用户消息"不是真指令，跳过
META_PREFIXES = ('This session is being continued', '<', 'Caveat:', '[Request interrupted',
                 'Context handoff', '# AGENTS.md', 'Base directory for this skill',
                 '[Workflow harness', '[UI language]', 'Your response above was cut off')


def msg_text(content):
    """把 message.content 归一成纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(x.get('text', '') for x in content
                        if isinstance(x, dict) and x.get('type') == 'text')
    return ''


def is_meta(text):
    """这条「用户消息」是不是系统噪声，不是真人指令。"""
    t = (text or '').strip()
    return not t or t.startswith(META_PREFIXES)


def pick_prompt(store, key, ts, text):
    """记下该来源最早的真人指令（按时间戳比，文件遍历顺序不可靠）。"""
    if is_meta(text):
        return
    cur = store.get(key)
    if cur is None:
        store[key] = (ts, text.strip())
        return
    old_ts = cur[0]
    if ts is not None and (old_ts is None or ts < old_ts):
        store[key] = (ts, text.strip())


def prompt_of(store, key):
    """取某来源记下的最早真人指令（截断 120 字）。"""
    ent = store.get(key)
    if not ent:
        return None
    return ent[1][:120]


def now_local():
    return datetime.datetime.now().astimezone()


def collect_agents(day):
    """Claude Code 日志 → [{name, source:'claude', cwd, spans, tokens, msgs}]"""
    files = glob.glob(str(HOME / '.claude/projects/**/*.jsonl'), recursive=True)
    seg = {}
    prompts = {}
    for f in files:
        proj = os.path.basename(os.path.dirname(f))
        realcwd = None
        for line in open(f, errors='replace'):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if realcwd is None and d.get('cwd'):
                realcwd = d['cwd']
            ts = d.get('timestamp')
            if d.get('type') == 'user':
                txt = msg_text((d.get('message') or {}).get('content'))
                if txt.strip():
                    pick_prompt(prompts, proj, ts, txt)
            if not ts:
                continue
            try:
                dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone()
            except Exception:
                continue
            if dt.date() != day:
                continue
            u = (d.get('message') or {}).get('usage') or {}
            seg.setdefault(proj, {'cwd': None, 'pts': []})
            if realcwd and not seg[proj]['cwd']:
                seg[proj]['cwd'] = realcwd
            seg[proj]['pts'].append((dt.timestamp(), u.get('output_tokens', 0)))

    out = []
    for proj, blob in seg.items():
        items = blob['pts']
        items.sort()
        spans, cur = [], [items[0][0], items[0][0]]
        for t, _ in items[1:]:
            if t - cur[1] <= GAP:
                cur[1] = t
            else:
                spans.append(cur)
                cur = [t, t]
        spans.append(cur)
        cwd = blob['cwd']
        name = (Path(cwd).name if cwd and Path(cwd).name else '') or humanize(proj)
        if cwd and str(cwd) == str(HOME):
            name = '家目录'
        # OpenBot 的 agent 目录名是 UUID，换成可读标签
        m = re.search(r'agent-([0-9a-f]{8})', cwd or proj)
        if m:
            name = f'OpenBot · {m.group(1)}'
        # 排除我自己的测试目录噪声
        if re.search(r'(^-private-tmp|/tmp/|/private/tmp|wtest|vault-copy)', (cwd or '') + proj):
            continue
        if re.fullmatch(r'tmp', name):
            continue
        out.append({
            'name': name,
            'cwd': cwd,
            'key': proj,
            'source': 'claude',
            'spans': spans,
            'tokens': sum(x[1] for x in items),
            'msgs': len(items),
            'first_prompt': prompt_of(prompts, proj),
        })
    out.sort(key=lambda r: -r['tokens'])
    return out


def collect_codex(day):
    """Codex CLI 日志（~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl）→ 同结构列表。

    结构：每行 {timestamp, type, payload}。
    - session_meta.payload.cwd = 工作目录
    - token_usage_record.payload = token 用量
    其余行只取时间戳当活动点。
    """
    files = glob.glob(str(HOME / '.codex/sessions/**/*.jsonl'), recursive=True)
    seg = {}
    prompts = {}
    out = []
    for f in files:
        # 文件路径里就有日期，先粗筛省得读 770MB 无关内容
        try:
            parts = Path(f).parts[-4:-1]   # .../sessions/2026/11/13/xxx.jsonl
            if datetime.date(int(parts[0]), int(parts[1]), int(parts[2])) != day:
                continue
        except Exception:
            pass
        cwd = None
        for line in open(f, errors='replace'):
            try:
                d = json.loads(line)
            except Exception:
                continue
            p = d.get('payload') or {}
            if cwd is None and p.get('cwd'):
                cwd = p['cwd']
                seg.setdefault(cwd, {'pts': []})
            if (d.get('type') == 'response_item' and p.get('type') == 'message'
                    and p.get('role') == 'user'):
                txt = ' '.join(x.get('text', '') for x in (p.get('content') or [])
                               if isinstance(x, dict))
                if txt.strip():
                    pick_prompt(prompts, cwd or '?', d.get('timestamp'), txt)
            ts = d.get('timestamp')
            if not ts:
                continue
            try:
                dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone()
            except Exception:
                continue
            if dt.date() != day:
                continue
            tok = 0
            if d.get('type') == 'token_usage_record':
                u = p.get('usage') or {}
                tok = u.get('output_tokens', 0)
            if cwd is not None:
                seg[cwd]['pts'].append((dt.timestamp(), tok))

    # 按 cwd 合并（同项目可能开多个会话文件）
    for cwd, blob in seg.items():
        pts = blob['pts']
        if not pts:
            continue
        name = Path(cwd).name if cwd and Path(cwd).name else 'Codex 会话'
        if cwd and str(cwd) == str(HOME):
            name = '家目录'
        m = re.search(r'agent-([0-9a-f]{8})', cwd or '')
        if m:
            name = f'OpenBot · {m.group(1)}'
        if re.search(r'(/tmp/|/private/tmp|wtest|vault-copy)', cwd or ''):
            continue
        pts.sort()
        spans, cur = [], [pts[0][0], pts[0][0]]
        for t, _ in pts[1:]:
            if t - cur[1] <= GAP:
                cur[1] = t
            else:
                spans.append(cur)
                cur = [t, t]
        spans.append(cur)
        out.append({
            'name': f'Codex · {name}' if not name.startswith('家目录') else name,
            'cwd': cwd,
            'key': cwd or 'codex',
            'source': 'codex',
            'spans': spans,
            'tokens': sum(x[1] for x in pts),
            'msgs': len(pts),
            'first_prompt': prompt_of(prompts, cwd or '?'),
        })
    out.sort(key=lambda r: -r['tokens'])
    return out


def humanize(proj):
    """把 claude 的目录编码还原成人能读的项目名。

    难点：编码把 / 和中文都变成 -，所以不能简单 replace。
    做法：拿候选路径去文件系统上反查，存在就认定。
    """
    # 家目录：编码后的 home 路径
    home_enc = HOME.as_posix().replace('/', '-').rstrip('-')
    if proj == home_enc or proj == f'-{HOME.name}':
        return '家目录'
    # 已知前缀
    if 'OpenBot-Agents-agent-' in proj:
        return 'OpenBot/' + proj.split('OpenBot-Agents-agent-')[-1][:8]
    if 'Application-Support-' in proj:
        return proj.split('Application-Support-')[-1][:18]
    if proj.startswith('-private-tmp'):
        return 'tmp' + proj[len('-private-tmp'):]

    # Code/Demos 下的项目：目录名是 ASCII，直接后缀匹配最可靠
    demos = HOME / 'Code' / 'Demos'
    if demos.exists():
        for d in sorted(demos.iterdir(), key=lambda p: -len(p.name)):
            if d.is_dir() and proj.endswith(d.name):
                return d.name

    # 其他路径：把编码还原成真实路径再去反查
    cand = proj.replace('-', '/')
    for pre in (f'/{HOME.name}/', '/private/'):
        if cand.startswith(pre):
            cand = cand[len(pre):]
            break
    real = HOME / cand if not cand.startswith('/') else Path(cand)
    if real.exists():
        return real.name or str(real)

    tail = proj.split('-')[-1]
    return (tail if len(tail) > 3 else proj[-24:]) or '未知'


def collect_todos(vault, day):
    """→ [{text, status, result}]"""
    diary = vault / '日记' / f'{day:%Y}' / f'{day:%Y-%m-%d}.md'
    if not diary.exists():
        cands = sorted((vault / '日记').rglob('*.md'),
                       key=lambda p: p.stat().st_mtime, reverse=True) if (vault / '日记').exists() else []
        if not cands:
            return [], None
        diary = cands[0]
    txt = diary.read_text(encoding='utf-8')
    out = []
    in_ai = False
    for line in txt.split('\n'):
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            in_ai = 'AI' in m.group(2) and ('代办' in m.group(2) or '待办' in m.group(2))
            continue
        if not in_ai:
            continue
        t = re.match(r'^\s*[-*+]\s+\[([ xX!~])\]\s+(.*)$', line)
        if t:
            body = t.group(2)
            task, _, res = body.partition(' → ')
            out.append({
                'text': task.strip(),
                'status': {' ': 'todo', 'x': 'done', 'X': 'done',
                           '!': 'blocked', '~': 'blocked'}[t.group(1)],
                'result': res.strip(),
            })
    return out, str(diary)


def collect_pi(day):
    """PI CLI 日志（~/.pi/agent/sessions/<编码cwd>/*.jsonl）→ 同结构列表。

    结构：jsonl，每行 {type, timestamp, ...}。
    - type=session 行带 cwd
    - type=message 行（assistant）的 message.usage 带 tokens
    目录名 --Users-xxx-Code-Demos-xxx-- 就是编码过的 cwd，但 session 行里有真 cwd。
    """
    files = glob.glob(str(HOME / '.pi/agent/sessions/*/*.jsonl'))
    seg = {}
    prompts = {}
    for f in files:
        # 文件名首段就是 UTC 起始时间，粗筛
        stem = Path(f).name[:10]      # 2026-11-09
        try:
            if datetime.date(*map(int, stem.split('-'))) > day:
                continue               # 只排除"开始晚于目标日"的；跨日会话保留
        except Exception:
            pass
        dirname = Path(f).parent.name  # 编码过的 cwd，cwd 读到之前先用它兜底
        cwd = None
        for line in open(f, errors='replace'):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if cwd is None and d.get('cwd'):
                cwd = d['cwd']
            ts = d.get('timestamp')
            if not ts:
                continue
            try:
                dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone()
            except Exception:
                continue
            m = d.get('message') or {}
            if d.get('type') == 'message' and m.get('role') == 'user':
                txt = msg_text(m.get('content'))
                if txt.strip():
                    # 同一会话前半段 cwd 可能是 None，key 会分裂；两类 key 都记
                    pick_prompt(prompts, cwd, ts, txt)
                    if cwd is None:
                        pick_prompt(prompts, dirname, ts, txt)
            if dt.date() != day:
                continue
            tok = 0
            if d.get('type') == 'message' and m.get('role') == 'assistant':
                u = m.get('usage') or {}
                tok = (u.get('output') or u.get('outputTokens')
                       or u.get('output_tokens') or 0)
            key = cwd or dirname
            seg.setdefault(key, {'cwd': cwd, 'pts': []})
            if cwd and not seg[key]['cwd']:
                seg[key]['cwd'] = cwd
            seg[key]['pts'].append((dt.timestamp(), tok))

    out = []
    for key, blob in seg.items():
        pts = blob['pts']
        if not pts:
            continue
        pts.sort()
        spans, cur = [], [pts[0][0], pts[0][0]]
        for t, _ in pts[1:]:
            if t - cur[1] <= GAP:
                cur[1] = t
            else:
                spans.append(cur)
                cur = [t, t]
        spans.append(cur)
        cwd = blob['cwd']
        name = Path(cwd).name if cwd and Path(cwd).name else 'PI 会话'
        if cwd and str(cwd) == str(HOME):
            name = '家目录'
        m = re.search(r'agent-([0-9a-f]{8})', cwd or '')
        if m:
            name = f'OpenBot · {m.group(1)}'
        if re.search(r'(/tmp/|/private/tmp|wtest|vault-copy)', cwd or ''):
            continue
        out.append({
            'name': f'PI · {name}' if not name.startswith('家目录') else name,
            'cwd': cwd,
            'key': str(key)[:60],
            'source': 'pi',
            'spans': spans,
            'tokens': sum(x[1] for x in pts),
            'msgs': len(pts),
            'first_prompt': prompt_of(prompts, cwd) or prompt_of(prompts, key),
        })
    out.sort(key=lambda r: -r['tokens'])
    return out


def collect_journal(vault, day):
    """从日记正文里抽 [HH:MM] 时间戳 → 人工记录时段（每条算 12 分钟上下文）"""
    diary = vault / '日记' / f'{day:%Y}' / f'{day:%Y-%m-%d}.md'
    if not diary.exists():
        return []
    out = []
    for line in diary.read_text(encoding='utf-8').split('\n'):
        m = re.match(r'^\s*[-*+]?\s*\[(\d{1,2}):(\d{2})\]\s*(.+)$', line)
        if not m:
            continue
        h, mi, text = int(m.group(1)), int(m.group(2)), m.group(3).strip()
        t = h * 3600 + mi * 60
        out.append({'t': t, 'time': f'{h:02d}:{mi:02d}', 'text': text})
    return out


def collect_calendar(day):
    try:
        r = subprocess.run(
            ['alma', 'calendar', 'events', '--from', f'{day:%Y-%m-%d}',
             '--to', f'{day:%Y-%m-%d}', '--json'],
            capture_output=True, text=True, timeout=30)
        d = json.loads(r.stdout)
        if isinstance(d, dict) and d.get('status') == 'error':
            return [], 'no-permission'
        evs = []
        for e in (d if isinstance(d, list) else d.get('events', [])):
            s = e.get('start') or e.get('startDate')
            en = e.get('end') or e.get('endDate')
            if not s:
                continue
            evs.append({'title': e.get('title') or e.get('summary', ''),
                        'start': s, 'end': en})
        return evs, 'ok'
    except FileNotFoundError:
        return [], 'unavailable'      # 没装 alma：正常情况，不是错误
    except Exception as e:
        return [], f'error: {e}'


def collect_all(vault, day):
    """采集某一天 → payload dict（不落盘，供 CLI 和 serve.py 共用）。"""
    vault = Path(vault)
    agents = collect_agents(day) + collect_codex(day) + collect_pi(day)
    agents.sort(key=lambda r: -r['tokens'])
    todos, diary = collect_todos(vault, day)
    events, cal_status = collect_calendar(day)
    journal = collect_journal(vault, day)

    return {
        'generated': now_local().isoformat(timespec='seconds'),
        'date': f'{day:%Y-%m-%d}',
        'vault': str(vault),
        'vault_name': vault.name,
        # Obsidian URI：点日记记录/待办时直接跳进对应笔记
        'diary_uri': (f'obsidian://open?vault={urllib.parse.quote(vault.name)}'
                      f'&file={urllib.parse.quote(str(Path(diary).relative_to(vault))[:-3])}'
                      if diary else None),
        'diary': diary,
        'calendar_status': cal_status,
        'events': events,
        'agents': agents,
        'todos': todos,
        'journal': journal,
        'totals': {
            'sessions': sum(len(a['spans']) for a in agents),
            'agents': len(agents),
            'tokens': sum(a['tokens'] for a in agents),
            'active_seconds': sum(b - a for ag in agents for a, b in ag['spans']),
            'by_source': {
                s: {'agents': sum(1 for a in agents if a['source'] == s),
                    'tokens': sum(a['tokens'] for a in agents if a['source'] == s)}
                for s in ('claude', 'codex', 'pi')
            },
        },
    }


def write_payload(payload, update_latest=True):
    """落盘：data-YYYY-MM-DD.json 按日期留档；data.json 指向最近一次采集。

    update_latest=False 时只写按日期的存档。serve.py 浏览历史日期时用这个，
    避免把 data.json（代表"今天"）改成过去某天。
    """
    day = payload['date']
    out = Path(__file__).parent / f'data-{day}.json'
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    if update_latest:
        latest = Path(__file__).parent / 'data.json'
        latest.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


def main():
    if len(sys.argv) < 2:
        print('用法: collect.py <Obsidian 库路径> [YYYY-MM-DD]', file=sys.stderr)
        sys.exit(1)
    vault = Path(os.path.expanduser(sys.argv[1]))
    if not vault.is_dir():
        raise SystemExit(f'✗ 库路径不存在: {vault}')
    day = datetime.date.today()
    if len(sys.argv) > 2:
        day = datetime.datetime.strptime(sys.argv[2], '%Y-%m-%d').date()

    payload = collect_all(vault, day)
    out = write_payload(payload)
    src = payload['totals']['by_source']
    print(f"✓ {out}")
    print(f"  日期 {payload['date']} | Claude {src['claude']['agents']} / "
          f"Codex {src['codex']['agents']} / PI {src['pi']['agents']} 个来源，"
          f"共 {payload['totals']['sessions']} 段 | 待办 {len(payload['todos'])} 条 | "
          f"日历 {payload['calendar_status']} | token {payload['totals']['tokens']:,}")


if __name__ == '__main__':
    main()
