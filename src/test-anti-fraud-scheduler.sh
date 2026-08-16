#!/bin/bash
# test-anti-fraud-scheduler.sh — review-scheduler.sh check_anti_fraud P1-10 集成验收
#
# 覆盖验收点:
#   1. check_anti_fraud 委托 anti-distortion-rules.py 计数（季度范围 + 结构化事件 ID）
#   2. R-31 ≥2 次 → 输出「触发 R-71」；R-32 ≥2 次 → 输出「触发 R-72」
#   3. 未触发场景 → 输出「未触发」
#   4. 事件目录缺失 → fail-open 按 0 计，不崩溃
#
# 运行: bash test-anti-fraud-scheduler.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEDULER="$SCRIPT_DIR/review-scheduler.sh"
ANTI_RULES="$SCRIPT_DIR/anti-distortion-rules.py"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TMP=$(mktemp -d)
pass=0
fail=0

# source 调度器会在仓库根创建 reviews/ archive/ profiles/ 运行时目录；
# 记录测试前是否存在，仅清理本测试新建的目录（兼容 macOS bash 3.2，不用关联数组）。
PREEXIST=""
for d in "$REPO_ROOT/reviews" "$REPO_ROOT/archive" "$REPO_ROOT/profiles"; do
    if [ -e "$d" ]; then PREEXIST="$PREEXIST|$d"; fi
done

cleanup() {
    for d in "$REPO_ROOT/reviews" "$REPO_ROOT/archive" "$REPO_ROOT/profiles"; do
        case "|$PREEXIST|" in
            *"|$d|"*) ;;   # 测试前已存在，不清理
            *) [ -e "$d" ] && rm -rf "$d" ;;
        esac
    done
    rm -rf "$TMP"
}
trap cleanup EXIT

# source 调度器（--help 阻止 main 执行，仅加载函数与全局）
source "$SCHEDULER" --help >/dev/null 2>&1

# 覆盖运行时全局：check_anti_fraud 使用 $SCORING_DIR/events
SCORING_DIR="$TMP/scoring"
EVENTS_ROOT="$SCORING_DIR/events"

# 本季度 3 个月份（与 check_anti_fraud 内部口径一致：QUARTER_END_MONTH 由调度器按当前月计算）
Y=$(date +"%Y")
Q_START=$(( QUARTER_END_MONTH - 2 ))
MONTHS=("$Y-$(printf "%02d" $((Q_START)))" "$Y-$(printf "%02d" $((Q_START + 1)))" "$Y-$(printf "%02d" $((Q_START + 2)))")

write_month() {
    local agent="$1" month="$2"
    shift 2
    local dir="$EVENTS_ROOT/$agent"
    mkdir -p "$dir"
    {
        echo "| 时间 | 任务 | 事件 | 积分 |"
        echo "|------|------|------|:---:|"
        for row in "$@"; do echo "$row"; done
    } > "$dir/$month.md"
}

# ---------- 验收点 1：R-31 ×2 → 触发 R-71 ----------
echo "== 验收点 1：R-31 季度内 ≥2 → 触发 R-71 =="
(
    write_month "测试智能体" "${MONTHS[0]}" \
        "| ${MONTHS[0]}-01 10:00 | i-1 | R-31:违反约束 | -20 |" \
        "| ${MONTHS[0]}-02 10:00 | i-2 | R-31:违反约束 | -20 |"
    out=$(check_anti_fraud "测试智能体")
    echo "$out"
    echo "$out" | grep -q "触发 R-71" || exit 1
    echo "$out" | grep -q "R-31 红线事件: 2 次" || exit 1
    echo "$out" | grep -q "R-32 缺自评事件: 0 次" || exit 1
)
if [ $? -eq 0 ]; then
    pass=$((pass + 1)); echo "  ✓ R-71 触发与计数正确"
else
    fail=$((fail + 1)); echo "  ✗ R-71 检查失败"
fi

# ---------- 验收点 2：R-32 ×2 → 触发 R-72 ----------
echo "== 验收点 2：R-32 季度内 ≥2 → 触发 R-72 =="
(
    write_month "测试智能体" "${MONTHS[0]}" \
        "| ${MONTHS[0]}-01 10:00 | i-1 | R-32:未提交自评 | -5 |" \
        "| ${MONTHS[0]}-02 10:00 | i-2 | R-32:未提交自评 | -5 |"
    out=$(check_anti_fraud "测试智能体")
    echo "$out"
    echo "$out" | grep -q "触发 R-72" || exit 1
    echo "$out" | grep -q "R-32 缺自评事件: 2 次" || exit 1
)
if [ $? -eq 0 ]; then
    pass=$((pass + 1)); echo "  ✓ R-72 触发与计数正确"
else
    fail=$((fail + 1)); echo "  ✗ R-72 检查失败"
fi

# ---------- 验收点 3：未触发场景 ----------
echo "== 验收点 3：单次 R-31 不触发 =="
(
    write_month "测试智能体" "${MONTHS[0]}" \
        "| ${MONTHS[0]}-01 10:00 | i-1 | R-31:违反约束 | -20 |"
    out=$(check_anti_fraud "测试智能体")
    echo "$out"
    echo "$out" | grep -q "未触发" || exit 1
    echo "$out" | grep -q "R-31 红线事件: 1 次" || exit 1
)
if [ $? -eq 0 ]; then
    pass=$((pass + 1)); echo "  ✓ 未触发与计数正确"
else
    fail=$((fail + 1)); echo "  ✗ 未触发检查失败"
fi

# ---------- 验收点 4：fail-open（事件目录缺失按 0 计） ----------
echo "== 验收点 4：事件目录缺失 fail-open =="
(
    out=$(check_anti_fraud "不存在智能体")
    echo "$out"
    echo "$out" | grep -q "R-31 红线事件: 0 次" || exit 1
    echo "$out" | grep -q "R-32 缺自评事件: 0 次" || exit 1
    echo "$out" | grep -q "未触发" || exit 1
)
if [ $? -eq 0 ]; then
    pass=$((pass + 1)); echo "  ✓ fail-open 按 0 计"
else
    fail=$((fail + 1)); echo "  ✗ fail-open 检查失败"
fi

echo ""
echo "======================================"
echo "结果: 通过 $pass 项, 失败 $fail 项"
echo "======================================"
[ "$fail" -eq 0 ]
