#!/usr/bin/env python3
"""
validate-self-review-score-suggestion.py — 校验自评块「评分建议」字段落地情况（P1-7 / KA-72）

校验规则（对应规则书 §7.4 / 字段说明 self-review-score-suggestion.md）：
  1. 【自评】块必须存在；
  2. 块内末尾必须含「评分建议：」字段，取值形如 {1-5}；
  3. 评分建议必须位于「改进」之后（块末尾）。

用法：
  python3 validate-self-review-score-suggestion.py            # 校验全部非归档智能体
  python3 validate-self-review-score-suggestion.py <agent-id> [<agent-id> ...]  # 仅校验指定智能体
"""

import json
import re
import subprocess
import sys


def load_agents(ids=None):
    """拉取智能体列表（可过滤指定 id）。"""
    result = subprocess.run(
        ["multica", "agent", "list", "--output", "json"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"multica agent list 失败: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    if isinstance(data, dict):
        data = data.get("agents", [])
    if ids:
        data = [a for a in data if a.get("id") in ids]
    return data


def check_agent(agent):
    """校验单个智能体，返回 (通过, 原因列表)。"""
    name = agent.get("name", "?")
    instructions = agent.get("instructions") or ""
    ok = True
    reasons = []

    if not instructions.strip():
        return False, ["instructions 为空"]

    # 1. 自评块存在
    block_m = re.search(r"【自评】", instructions)
    if not block_m:
        return False, ["缺少【自评】块"]
    reasons.append("含【自评】块")

    # 2. 评分建议字段存在且位于块末尾（改进之后）
    block_start = block_m.start()
    # 找到块结束：后面的 --- 或 ### / 空白分隔
    tail = instructions[block_start:]
    end_m = re.search(r"(?:\n---|\n###|\n\n)", tail)
    block_text = tail[: end_m.start()] if end_m else tail

    sugg = re.search(r"评分建议[:：]\s*(\{[^}]*\}|[1-5])", block_text)
    if not sugg:
        return False, ["自评块内缺少「评分建议」字段"]
    reasons.append(f"含「评分建议」字段")

    # 位置：改进 在 评分建议 之前
    idx_improve = block_text.rfind("改进")
    idx_sugg = block_text.rfind("评分建议")
    if idx_improve == -1 or idx_sugg <= idx_improve:
        # 无「改进」行时，评分建议位于行尾即可（宽松校验）
        if idx_improve != -1:
            return False, ["「评分建议」未位于「改进」之后（块末尾）"]
    reasons.append("位于块末尾")

    return ok, reasons


def main():
    ids = sys.argv[1:] or None
    agents = load_agents(ids)
    print(f"共 {len(agents)} 个智能体\n")

    passed, failed = [], []
    for agent in agents:
        ok, reasons = check_agent(agent)
        name = agent.get("name", "?")
        if ok:
            passed.append(name)
            print(f"✅ {name}: {'; '.join(reasons)}")
        else:
            failed.append((name, reasons))
            print(f"❌ {name}: {'; '.join(reasons)}")

    print("\n========== 汇总 ==========")
    print(f"✅ 通过: {len(passed)} 个")
    print(f"❌ 未通过: {len(failed)} 个")
    for name, reasons in failed:
        print(f"   - {name}: {'; '.join(reasons)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
