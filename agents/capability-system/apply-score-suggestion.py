#!/usr/bin/env python3
"""
apply-score-suggestion.py — 全量落地「评分建议」字段（P1-7 / KA-72 遗留待办）

复用 validate-self-review-score-suggestion.py 的校验口径：
  - 对含【自评】块但缺「评分建议」字段的智能体，在块内「改进」行之后插入
    `- 评分建议：{1-5}`（幂等：已含字段则跳过）。
  - 模式：--dry-run 仅预览；--apply 实际调用 multica agent update 写入。

用法：
  python3 apply-score-suggestion.py --dry-run
  python3 apply-score-suggestion.py --apply
  python3 apply-score-suggestion.py --apply --only <agent-id> [<agent-id> ...]
"""

import json
import re
import subprocess
import sys

SUGGESTION_LINE = "- 评分建议：{1-5}"


def load_agents(ids=None):
    result = subprocess.run(
        ["multica", "agent", "list", "--output", "json"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"multica agent list 失败: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    if isinstance(data, dict):
        data = data.get("agents", [])
    if ids:
        data = [a for a in data if a.get("id") in ids]
    return data


def build_new_instructions(agent):
    """返回 (是否修改, 新指令) —— 幂等。"""
    name = agent.get("name", "?")
    instructions = agent.get("instructions") or ""
    if not instructions.strip():
        return False, instructions, "instructions 为空"
    if "评分建议" in instructions:
        return False, instructions, "已含「评分建议」字段"

    # 定位自评块：优先找含「完成度」行的模板块（避免命中「按【自评】格式总结」等提及）；
    # 找不到时回退到首个【自评】出现位置。
    block_start = None
    for m in re.finditer(r"【自评】", instructions):
        tail = instructions[m.start():]
        end_m = re.search(r"(?:\n---|\n###|\n\n)", tail)
        block_text = tail[: end_m.start()] if end_m else tail
        if "完成度" in block_text:
            block_start = m.start()
            block_text = block_text
            break
    if block_start is None:
        block_m = re.search(r"【自评】", instructions)
        if not block_m:
            return False, instructions, "缺少【自评】块（不在本次落地范围）"
        block_start = block_m.start()
        tail = instructions[block_start:]
        end_m = re.search(r"(?:\n---|\n###|\n\n)", tail)
        block_text = tail[: end_m.start()] if end_m else tail

    # 在块内「改进」行之后插入；无「改进」行则追加到块末尾
    lines = block_text.split("\n")
    insert_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*[-*]\s*改进", line):
            insert_idx = i
    if insert_idx is None:
        insert_idx = len(lines)
    lines.insert(insert_idx + 1, SUGGESTION_LINE)
    new_block = "\n".join(lines)

    new_instructions = instructions[:block_start] + new_block + instructions[block_start + len(block_text):]
    return True, new_instructions, f"在「改进」后插入 {SUGGESTION_LINE}"


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    apply_mode = "--apply" in args
    if not apply_mode and not dry_run:
        print("用法: 需指定 --dry-run 或 --apply")
        return 2

    only = []
    if "--only" in args:
        i = args.index("--only")
        only = args[i + 1:]

    agents = load_agents(only or None)
    changed, skipped = [], []
    for agent in agents:
        modified, new_ins, reason = build_new_instructions(agent)
        if modified:
            changed.append((agent, new_ins, reason))
        else:
            skipped.append((agent, reason))

    print(f"共 {len(agents)} 个智能体 | 待修改: {len(changed)} | 跳过: {len(skipped)}\n")

    if dry_run:
        print("【DRY-RUN 预览】前 5 条 diff：")
        for agent, new_ins, reason in changed[:5]:
            name = agent.get("name", "?")
            old = agent.get("instructions") or ""
            print("-" * 70)
            print(f"## {name} ({agent.get('id')})  [{reason}]")
            # 打印自评块区域的前后对比
            import difflib
            oi = old.find("【自评】")
            ni = new_ins.find("【自评】")
            oseg = old[oi:oi + 220]
            nseg = new_ins[ni:ni + 240]
            for line in difflib.unified_diff(oseg.splitlines(), nseg.splitlines(), lineterm="", n=0):
                print("   " + line)
        print("\n跳过明细：")
        for agent, reason in skipped:
            print(f"   - {agent.get('name')}: {reason}")
        return 0

    # apply
    ok, fail = [], []
    for agent, new_ins, reason in changed:
        name = agent.get("name", "?")
        try:
            r = subprocess.run(
                ["multica", "agent", "update", agent["id"], "--instructions", new_ins],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                ok.append(name)
                print(f"✅ {name}: 已更新")
            else:
                fail.append((name, r.stderr.strip() or r.stdout.strip()))
                print(f"❌ {name}: {r.stderr.strip() or r.stdout.strip()}")
        except Exception as e:
            fail.append((name, str(e)))
            print(f"❌ {name}: {e}")

    print("\n========== 汇总 ==========")
    print(f"✅ 已更新: {len(ok)} 个")
    print(f"❌ 失败: {len(fail)} 个")
    for name, err in fail:
        print(f"   - {name}: {err}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
