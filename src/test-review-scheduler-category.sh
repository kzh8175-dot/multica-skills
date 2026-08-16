#!/bin/bash
# test-review-scheduler-category.sh — review-scheduler.sh R-42 类别解析验收测试（KA-43）
#
# 覆盖验收点:
#   1. 9 个关键智能体在调度侧取到的类别/基准 == R-42 映射
#      （SEO类→marketing/350、社交/销售类→marketing/350、轮播图/短视频剪辑→creative/300）
#   2. 幂等：重复运行 get_agent_category 结果一致
#   3. 无回归：非 9 个智能体其余类别/基准不变（与旧逻辑档案+关键词基线一致）
#   4. multica CLI 不可用时回退到档案+关键词（无破坏性变更）
#
# 运行: bash test-review-scheduler-category.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEDULER="$SCRIPT_DIR/review-scheduler.sh"

# 独立缓存文件：保证本次测试自包含、可复现（不依赖外部残留缓存）。
# source 会按 "$TMPDIR" 初始化缓存路径，故在 source 后统一覆盖该全局变量。
TEST_CACHE=$(mktemp -t ka43-agent-cats-XXXXXX)
rm -f "$TEST_CACHE"

pass=0
fail=0

# source 脚本（--help 使顶层 main 不执行）并注入独立缓存路径。
# source 会执行 mkdir/echo 等初始化，属幂等无害操作。
# 之后所有 get_agent_category 调用（含 $(...) 子 shell）通过文件缓存共享 CLI 数据。
source_sched() {
    source "$SCHEDULER" --help >/dev/null 2>&1
    _AGENT_CLI_CATS_CACHE="$TEST_CACHE"
}

# ---------- 验收点 1：9 个关键智能体类别/基准 == R-42 ----------
echo "== 验收点 1：9 个关键智能体类别/基准 == R-42 =="
(
    source_sched
    ok=1
    for e in "SEO优化专家 marketing 350" "百度SEO专家 marketing 350" \
             "视频优化专家 marketing 350" "中国市场本地化策略师 marketing 350" \
             "社交媒体师 marketing 350" "销售工程师 marketing 350" "销售教练 marketing 350" \
             "短视频剪辑教练专家 creative 300" "轮播图自动生成专家 creative 300"; do
        set -- $e
        name="$1"; want_cat="$2"; want_bench="$3"
        got_cat=$(get_agent_category "$name")
        got_bench=$(get_benchmark "$got_cat")
        if [ "$got_cat" = "$want_cat" ] && [ "$got_bench" = "$want_bench" ]; then
            echo "    ✓ $name → $got_cat/$got_bench"
        else
            echo "    ✗ $name → got $got_cat/$got_bench, want $want_cat/$want_bench"
            ok=0
        fi
    done
    [ "$ok" -eq 1 ]
)
if [ $? -eq 0 ]; then
    pass=$((pass + 1)); echo "  ✓ 验收点1通过"
else
    fail=$((fail + 1)); echo "  ✗ 验收点1失败（见上方）"
fi

# ---------- 验收点 2：幂等 ----------
echo "== 验收点 2：幂等（两次运行结果一致） =="
IDEM_A=$(mktemp); IDEM_B=$(mktemp)
(
    source_sched
    for d in "$PROFILES_DIR"/*/; do [ -d "$d" ] || continue; n=$(basename "$d"); echo "$n $(get_agent_category "$n") $(get_benchmark "$(get_agent_category "$n")")"; done | sort
) > "$IDEM_A"
(
    source_sched
    for d in "$PROFILES_DIR"/*/; do [ -d "$d" ] || continue; n=$(basename "$d"); echo "$n $(get_agent_category "$n") $(get_benchmark "$(get_agent_category "$n")")"; done | sort
) > "$IDEM_B"
if diff -q "$IDEM_A" "$IDEM_B" >/dev/null; then
    pass=$((pass + 1)); echo "  ✓ 两次运行类别/基准完全一致（幂等）"
else
    fail=$((fail + 1)); echo "  ✗ 两次运行结果不一致"; diff "$IDEM_A" "$IDEM_B"
fi
rm -f "$IDEM_A" "$IDEM_B"

# ---------- 验收点 3：无回归（非 9 个智能体类别与旧逻辑基线一致） ----------
echo "== 验收点 3：无回归（非 9 个智能体类别与旧逻辑基线一致） =="
(
    source_sched
    # 复刻旧 get_agent_category（档案 category + 关键词推断，不含 CLI 标签）
    old_get_agent_category() {
        local agent_name="$1"
        local profile_file="$PROFILES_DIR/${agent_name}/capabilities.md"
        if [ -f "$profile_file" ]; then
            local cat_line
            cat_line=$(grep -o "category[=: ]*[a-z]*" "$profile_file" 2>/dev/null | head -1 | grep -o "[a-z]*$" || true)
            if [ -n "$cat_line" ]; then
                case "$cat_line" in
                    execution|data|marketing|creative|technical) echo "$cat_line"; return ;;
                esac
            fi
        fi
        case "$agent_name" in
            *运营*|*客服*|*零售*|*Jira*|*会议*) echo "execution" ;;
            *财务*|*分析*|*数据*|*实验*|*趋势*|*文档*) echo "data" ;;
            *抖音*|*快手*|*小红书*|*知乎*|*微博*|*增长*|*内容*|*社媒*|*营销*|*播客*|*轮播*|*出版*|*微信*|*B站*) echo "marketing" ;;
            *战略*|*品牌*|*视觉*|*UI*|*设计*|*产品*) echo "creative" ;;
            *架构*|*身份*|*自动化*|*流程*|*工作流*|*SEO*|*搜索*|*本地化*|*视频*|*剪辑*) echo "technical" ;;
            *) echo "execution" ;;
        esac
    }
    n=0; rc=0
    for d in "$PROFILES_DIR"/*/; do
        [ -d "$d" ] || continue
        name=$(basename "$d")
        case "$name" in
            SEO优化专家|百度SEO专家|视频优化专家|中国市场本地化策略师|社交媒体师|销售工程师|销售教练|短视频剪辑教练专家|轮播图自动生成专家) continue ;;
        esac
        old_cat=$(old_get_agent_category "$name")
        new_cat=$(get_agent_category "$name")
        if [ "$old_cat" != "$new_cat" ]; then
            echo "    ✗ 回归: $name old=$old_cat new=$new_cat"
            rc=1
        fi
        n=$((n + 1))
    done
    echo "    对比 ${n} 个非 9 对象"
    [ "$rc" -eq 0 ]
)
if [ $? -eq 0 ]; then
    pass=$((pass + 1)); echo "  ✓ 非 9 个智能体类别全部与旧逻辑基线一致（无回归）"
else
    fail=$((fail + 1)); echo "  ✗ 无回归检查失败（见上方）"
fi

# ---------- 验收点 4：CLI 不可用时回退档案+关键词 ----------
echo "== 验收点 4：multica 不可用时回退档案+关键词（无破坏性） =="
(
    source_sched
    _AGENT_CLI_CATS_LOADED=0
    _AGENT_CLI_CATS=""
    _AGENT_CLI_CATS_CACHE="/nonexistent/ka43-cache-$$.tmp"   # 强制重新拉取
    PATH=/usr/bin:/bin   # 隐藏 multica/python3
    load_agent_cli_categories
    if [ -n "$_AGENT_CLI_CATS" ]; then
        echo "    ✗ CLI 不可用但缓存非空"
        exit 1
    fi
    if [ -n "$(get_cli_agent_category "SEO优化专家")" ]; then
        echo "    ✗ CLI 缺失时仍返回类别"
        exit 1
    fi
    exit 0
)
if [ $? -eq 0 ]; then
    pass=$((pass + 1)); echo "  ✓ CLI 不可用时静默回退档案+关键词（无破坏性）"
else
    fail=$((fail + 1)); echo "  ✗ CLI 回退检查失败"
fi

rm -f "$TEST_CACHE"

echo ""
echo "======================================"
echo "结果: 通过 $pass 项, 失败 $fail 项"
echo "======================================"
[ "$fail" -eq 0 ]
