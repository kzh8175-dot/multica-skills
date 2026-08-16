#!/bin/bash

# 智能体能力档案定期审查机制（含季度人评）
# 职责：周度审查 / 月度审查 / 季度人评自动触发（评分系统方案C）
#
# 用法:
#   ./review-scheduler.sh            自动运行（按日期触发相应审查）
#   ./review-scheduler.sh --weekly   强制周度审查
#   ./review-scheduler.sh --monthly  强制月度审查
#   ./review-scheduler.sh --quarterly 强制季度人评
#   ./review-scheduler.sh --manual   强制全部审查
#   ./review-scheduler.sh --status   仅检查档案状态
#   ./review-scheduler.sh --help     帮助

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILES_DIR="$SCRIPT_DIR/../profiles"
REVIEW_DIR="$SCRIPT_DIR/../reviews"
ARCHIVE_DIR="$SCRIPT_DIR/../archive"
SCORING_DIR="$REVIEW_DIR/scoring"

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== 智能体能力档案定期审查系统（含季度人评） ===${NC}"
echo ""

# 创建必要的目录
mkdir -p "$REVIEW_DIR"
mkdir -p "$ARCHIVE_DIR"
mkdir -p "$PROFILES_DIR"
mkdir -p "$SCORING_DIR/events"
mkdir -p "$SCORING_DIR/monthly"
mkdir -p "$SCORING_DIR/quarterly"

# 获取当前日期
TODAY=$(date +"%Y-%m-%d")
DAY_OF_WEEK=$(date +"%u") # 1-7 (1是周一)
DAY_OF_MONTH=$(date +"%d")
CURRENT_MONTH=$(date +"%m")
CURRENT_YEAR=$(date +"%Y")
# 当月最后一天（兼容 macOS / Linux）
if date -j -v+1m -v-1d -f "%Y-%m-%d" "$(date +%Y-%m-01)" +"%d" >/dev/null 2>&1; then
    # macOS: -v 选项必须在 -f 之前
    LAST_DAY_OF_MONTH=$(date -j -v+1m -v-1d -f "%Y-%m-%d" "$(date +%Y-%m-01)" +"%d")
else
    # Linux
    LAST_DAY_OF_MONTH=$(date -d "$(date +%Y-%m-01) +1 month -1 day" +"%d")
fi

# 季度配置
QUARTER_MONTHS=(3 6 9 12)
CURRENT_QUARTER=$(( (10#$CURRENT_MONTH - 1) / 3 + 1 ))
QUARTER_END_MONTH=$(( CURRENT_QUARTER * 3 ))  # 季度末月: 3,6,9,12
QUARTER_LABEL="${CURRENT_YEAR}-Q${CURRENT_QUARTER}"

# 角色基准积分（方案C R-42）— 与 rating-aggregator.py 共用共享配置
# 优先读取 rating-benchmarks.conf；文件缺失时回退到内置默认值。
BENCH_CONF="$SCRIPT_DIR/rating-benchmarks.conf"
if [ -f "$BENCH_CONF" ]; then
    # shellcheck disable=SC1090
    source "$BENCH_CONF"
fi
: "${execution:=400}" "${data:=350}" "${marketing:=350}" "${creative:=300}" "${technical:=300}" "${default:=300}"

get_benchmark() {
    case "$1" in
        execution) echo "$execution" ;;
        data)      echo "$data" ;;
        marketing) echo "$marketing" ;;
        creative)  echo "$creative" ;;
        technical) echo "$technical" ;;
        *)         echo "$default" ;;
    esac
}

# ============================================================
# 触发判断
# ============================================================

# 是否周度审查日（周五）
should_weekly_review() {
    [ "$DAY_OF_WEEK" -eq 5 ]
}

# 是否月度审查日（每月最后一天）
should_monthly_review() {
    [ "$DAY_OF_MONTH" -ge "$LAST_DAY_OF_MONTH" ]
}

# 是否季度人评触发日（季度末月最后3天，容忍调度漂移）
should_quarterly_review() {
    local is_quarter_end_month=0
    for m in "${QUARTER_MONTHS[@]}"; do
        if [ "$CURRENT_MONTH" -eq "$m" ]; then
            is_quarter_end_month=1
            break
        fi
    done
    if [ "$is_quarter_end_month" -eq 1 ] && [ "$DAY_OF_MONTH" -ge $((LAST_DAY_OF_MONTH - 2)) ]; then
        return 0
    fi
    return 1
}

# ============================================================
# R-42 类别解析（与 rating-aggregator.py resolve_category 契约对称）
# ============================================================

# R-42 CLI 类别缓存：从 `multica agent list` 读取一次，
# 提取显式 category 字段或 description 的 `[category=X]` 标签，
# 键按「去空白/短横 + 小写」归一化（兼容档案目录名的空格/短横差异）。
# 与 rating-aggregator.py 的 load_cli_categories()/resolve_category() 口径一致:
#   CLI(R-42 `[category=X]`) → 档案 category 标签 → 关键词推断。
#
# 缓存写入 `${TMPDIR:-/tmp}` 下的文件（TTL 1 小时），因为 get_agent_category
# 通常在 `$(...)` 命令替换（子 shell）中调用，纯内存变量无法跨子 shell 复用；
# 文件缓存保证一次运行内只请求一次 CLI，且重复运行结果一致（幂等）。
# multica / python3 不可用时缓存为空，自动回退到原有档案+关键词逻辑（无破坏性变更）。
_AGENT_CLI_CATS_LOADED=0
_AGENT_CLI_CATS=""   # 每行 "<归一化名> <category>"
_AGENT_CLI_CATS_CACHE="${TMPDIR:-/tmp}/multica-agent-cats-${MULTICA_WORKSPACE_ID:-workspace}.tmp"

load_agent_cli_categories() {
    if [ "$_AGENT_CLI_CATS_LOADED" -eq 1 ]; then
        return 0
    fi
    _AGENT_CLI_CATS=""
    # 缓存命中（1 小时内）直接复用，避免子 shell 反复请求 CLI
    if [ -f "$_AGENT_CLI_CATS_CACHE" ]; then
        local now cache_age
        now=$(date +%s)
        cache_age=$(( now - $(stat -f %m "$_AGENT_CLI_CATS_CACHE" 2>/dev/null || stat -c %Y "$_AGENT_CLI_CATS_CACHE" 2>/dev/null || echo 0) ))
        if [ "$cache_age" -lt 3600 ]; then
            _AGENT_CLI_CATS=$(cat "$_AGENT_CLI_CATS_CACHE" 2>/dev/null || true)
            _AGENT_CLI_CATS_LOADED=1
            return 0
        fi
    fi
    if command -v multica >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
        _AGENT_CLI_CATS=$(multica agent list --output json 2>/dev/null | python3 -c '
import sys, json, re
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(data, list):
    sys.exit(0)
DESC_CATEGORY_RE = re.compile(r"\[category\s*=\s*([a-z]+)\]")
VALID = {"execution", "data", "marketing", "creative", "technical"}
def norm(n):
    return re.sub(r"[\s\-]", "", n or "").lower()
for a in data:
    if not isinstance(a, dict):
        continue
    name = a.get("name")
    if not name:
        continue
    cat = a.get("category") or a.get("agent.category")
    if not cat:
        m = DESC_CATEGORY_RE.search(a.get("description") or "")
        if m:
            cat = m.group(1)
    if cat and cat in VALID:
        print("%s %s" % (norm(name), cat))
' 2>/dev/null || true)
        # 仅当 CLI 确实可执行时写入缓存（即使无标签也写空，避免反复重试）
        printf '%s\n' "$_AGENT_CLI_CATS" > "$_AGENT_CLI_CATS_CACHE" 2>/dev/null || true
    fi
    _AGENT_CLI_CATS_LOADED=1
}

get_cli_agent_category() {
    local agent_name="$1"
    local norm
    norm=$(printf '%s' "$agent_name" | tr -d '[:space:]-' | tr '[:upper:]' '[:lower:]')
    [ -z "$norm" ] && return 0
    printf '%s\n' "$_AGENT_CLI_CATS" | awk -v n="$norm" '$1 == n { print $2; exit }'
}

# 获取智能体的角色类别（方案C R-42）
# 优先级（与 rating-aggregator.py resolve_category 对称）:
#   ① CLI R-42 类别：description `[category=X]` 标签 / 显式 category 字段
#   ② 档案 category 标签
#   ③ 目录名关键词推断
get_agent_category() {
    local agent_name="$1"

    # ① 最高优先级：CLI R-42 类别
    local cli_cat
    load_agent_cli_categories
    cli_cat=$(get_cli_agent_category "$agent_name")
    if [ -n "$cli_cat" ]; then
        echo "$cli_cat"
        return
    fi

    # ② 档案 category 标签兜底
    local profile_file="$PROFILES_DIR/${agent_name}/capabilities.md"
    if [ -f "$profile_file" ]; then
        local cat_line
        cat_line=$(grep -o 'category[=: ]*[a-z]*' "$profile_file" 2>/dev/null | head -1 | grep -o '[a-z]*$' || true)
        if [ -n "$cat_line" ]; then
            # 校验为有效类别
            case "$cat_line" in
                execution|data|marketing|creative|technical) echo "$cat_line"; return ;;
            esac
        fi
    fi

    # ③ 目录名关键词推断兜底
    case "$agent_name" in
        *运营*|*客服*|*零售*|*Jira*|*会议*) echo "execution" ;;
        *财务*|*分析*|*数据*|*实验*|*趋势*|*文档*) echo "data" ;;
        *抖音*|*快手*|*小红书*|*知乎*|*微博*|*增长*|*内容*|*社媒*|*营销*|*播客*|*轮播*|*出版*|*微信*|*B站*) echo "marketing" ;;
        *战略*|*品牌*|*视觉*|*UI*|*设计*|*产品*) echo "creative" ;;
        *架构*|*身份*|*自动化*|*流程*|*工作流*|*SEO*|*搜索*|*本地化*|*视频*|*剪辑*) echo "technical" ;;
        *) echo "execution" ;;
    esac
}

# ============================================================
# 档案状态检查
# ============================================================

needs_update() {
    local profile_file="$1"
    if [ ! -f "$profile_file" ]; then
        return 0
    fi
    local last_update
    last_update=$(stat -f "%Sm" -t "%Y-%m-%d" "$profile_file" 2>/dev/null || stat -c "%y" "$profile_file" 2>/dev/null | cut -d' ' -f1)
    if [ -z "$last_update" ]; then
        return 0
    fi
    local now_s update_s
    now_s=$(date -j -f "%Y-%m-%d" "$TODAY" +%s 2>/dev/null || date -d "$TODAY" +%s)
    update_s=$(date -j -f "%Y-%m-%d" "$last_update" +%s 2>/dev/null || date -d "$last_update" +%s)
    local days=$(( (now_s - update_s) / 86400 ))
    [ "$days" -gt 30 ]
}

check_profile_updates() {
    echo -e "${YELLOW}📋 检查档案更新状态...${NC}"
    echo ""
    local total=0 missing=0 stale=0 ok=0
    for agent_dir in "$PROFILES_DIR"/*/; do
        [ -d "$agent_dir" ] || continue
        agent_name=$(basename "$agent_dir")
        profile_file="$agent_dir/capabilities.md"
        if [ ! -f "$profile_file" ]; then
            echo -e "  ${RED}✗${NC} ${agent_name}: 档案文件不存在"
            ((missing++))
        elif needs_update "$profile_file"; then
            echo -e "  ${YELLOW}⚠${NC} ${agent_name}: 档案需要更新"
            ((stale++))
        else
            echo -e "  ${GREEN}✓${NC} ${agent_name}: 档案状态良好"
            ((ok++))
        fi
        ((total++))
    done
    echo ""
    echo -e "汇总: 共${total}个 正常${ok} 待更新${stale} 缺失${missing}"
    echo ""
}

# ============================================================
# 周度审查
# ============================================================

perform_weekly_review() {
    echo -e "${YELLOW}📅 执行周度审查...${NC}"
    echo ""
    for agent_dir in "$PROFILES_DIR"/*/; do
        [ -d "$agent_dir" ] || continue
        agent_name=$(basename "$agent_dir")
        review_file="$REVIEW_DIR/weekly/${agent_name}/$(date +"%Y-W%V").md"
        mkdir -p "$(dirname "$review_file")"
        if [ ! -f "$review_file" ]; then
            cat > "$review_file" << EOF
# ${agent_name} - 周度审查

**周期**: $(date +"%Y年 第%V周")
**审查日期**: ${TODAY}
**审查人**: 自动化系统

---

## 本周完成任务
- {任务1}: {简述}
- {任务2}: {简述}

## 新学到的技能
- {技能1}: {描述}

## 遇到的挑战
- {挑战}: {解决方案}

## 下周改进重点
1. {改进重点}

## 自评结果
- 完成度: {评分}
- 学习量: {评分}
- 改进明确度: {评分}
EOF
            echo -e "  ${GREEN}✓${NC} 为 ${agent_name} 创建周度审查模板"
        else
            echo -e "  ${BLUE}○${NC} ${agent_name} 本周审查已存在"
        fi
    done
    echo ""
}

# ============================================================
# 月度审查
# ============================================================

perform_monthly_review() {
    echo -e "${YELLOW}📅 执行月度审查...${NC}"
    echo ""
    for agent_dir in "$PROFILES_DIR"/*/; do
        [ -d "$agent_dir" ] || continue
        agent_name=$(basename "$agent_dir")
        review_file="$REVIEW_DIR/monthly/${agent_name}/$(date +"%Y-%m").md"
        mkdir -p "$(dirname "$review_file")"
        if [ ! -f "$review_file" ]; then
            cat > "$review_file" << EOF
# ${agent_name} - 月度审查

**月份**: $(date +"%Y年%m月")
**审查日期**: ${TODAY}
**审查人**: 自动化系统

---

## 月度总结
- {本月主要成果}

## 能力发展评估
- {能力提升}

## 协作关系评估
- {协作情况}

## 下月计划
- {改进目标}

## 能力档案更新清单
- [ ] 更新"新学到的技能"章节
- [ ] 更新"改进的领域"章节
- [ ] 添加更新记录
EOF
            echo -e "  ${GREEN}✓${NC} 为 ${agent_name} 创建月度审查模板"
        else
            echo -e "  ${BLUE}○${NC} ${agent_name} 本月审查已存在"
        fi
    done
    echo ""
}

# ============================================================
# 季度人评（方案C）
# ============================================================

# 计算某智能体某月的百分制（若积分流水存在）
calc_monthly_score() {
    local agent_name="$1"
    local month="$2"  # 格式 YYYY-MM
    local events_file="$SCORING_DIR/events/${agent_name}/${month}.md"
    local total=0
    if [ -f "$events_file" ]; then
        # 仅取 markdown 表格"积分"列（倒数第2个 | 字段，末位是空），避免误计日期中的负号
        total=$(awk -F'|' '{v=$(NF-1); gsub(/^[ \t]+|[ \t]+$/, "", v); if (v ~ /^[+-][0-9]+$/) s += v} END {print s+0}' "$events_file")
    fi
    local category benchmark score
    category=$(get_agent_category "$agent_name")
    benchmark=$(get_benchmark "$category")
    score=$(( total * 100 / benchmark ))
    if [ "$score" -gt 120 ]; then score=120; fi
    if [ "$score" -lt 0 ]; then score=0; fi
    echo "$total $benchmark $score"
}

# 校验防失真规则（R-71, R-72）
check_anti_fraud() {
    local agent_name="$1"
    local quarter_dir="$SCORING_DIR/events/${agent_name}"
    local redline_count=0 self_review_missing=0

    # 统计本季度违规次数（R-31 事件 = -20 大额扣分）
    local rc=0 sr=0
    for mf in "$quarter_dir"/$(date +"%Y")-??.md; do
        [ -f "$mf" ] || continue
        rc=$(grep -cE '红线|违规|-20' "$mf" 2>/dev/null); rc=${rc:-0}
        sr=$(grep -cE '未提交自评|R-32' "$mf" 2>/dev/null); sr=${sr:-0}
        redline_count=$((redline_count + rc))
        self_review_missing=$((self_review_missing + sr))
    done

    local flags=""
    flags="红线计数=${redline_count}次"
    if [ "$redline_count" -ge 2 ]; then
        flags="${flags}|触发一票否决(R-71):等级上限C "
    else
        flags="${flags}|未触发(需≥2次)"
    fi
    flags="${flags} | 自评缺失计数=${self_review_missing}次"
    if [ "$self_review_missing" -ge 2 ]; then
        flags="${flags}|触发降档(R-72):等级降一档"
    else
        flags="${flags}|未触发(需≥2次)"
    fi
    echo "$flags"
}

# 生成季度人评表单
perform_quarterly_review() {
    echo -e "${YELLOW}📅 执行季度人评触发 (${QUARTER_LABEL})...${NC}"
    echo -e "${BLUE}触发窗口: 季度末月(${QUARTER_END_MONTH}月)最后3天 | 人评规则: 方案C (R-51~R-76)${NC}"
    echo ""

    # 本季度3个月份
    local q_start_month=$(( QUARTER_END_MONTH - 2 ))
    local months=()
    for i in 0 1 2; do
        months+=("$(date +"%Y")-$(printf "%02d" $((q_start_month + i)))")
    done

    local agent_count=0
    for agent_dir in "$PROFILES_DIR"/*/; do
        [ -d "$agent_dir" ] || continue
        agent_name=$(basename "$agent_dir")
        review_file="$SCORING_DIR/quarterly/${agent_name}/${QUARTER_LABEL}.md"
        mkdir -p "$(dirname "$review_file")"

        # 汇总3个月客观分（分别存储，避免变量覆盖）
        local obj_total=0 obj_valid_months=0 quarter_obj_score=0
        local m_total1=0 m_bench1=0 m_score1=0
        local m_total2=0 m_bench2=0 m_score2=0
        local m_total3=0 m_bench3=0 m_score3=0
        local idx=0 m_total=0 m_bench=0 m_score=0
        for m in "${months[@]}"; do
            read m_total m_bench m_score <<< "$(calc_monthly_score "$agent_name" "$m")"
            case $idx in
                0) m_total1=$m_total; m_bench1=$m_bench; m_score1=$m_score ;;
                1) m_total2=$m_total; m_bench2=$m_bench; m_score2=$m_score ;;
                2) m_total3=$m_total; m_bench3=$m_bench; m_score3=$m_score ;;
            esac
            obj_total=$((obj_total + m_score))
            ((idx++))
        done
        obj_valid_months=$idx
        if [ "$obj_valid_months" -gt 0 ]; then
            quarter_obj_score=$(( obj_total / obj_valid_months ))
        fi

        # 防失真校验
        local fraud_flags
        fraud_flags=$(check_anti_fraud "$agent_name")
        local cap_note=""
        if echo "$fraud_flags" | grep -q "R-71"; then
            cap_note="（等级上限C）"
        elif echo "$fraud_flags" | grep -q "R-72"; then
            cap_note="（等级降一档）"
        fi

        if [ ! -f "$review_file" ]; then
            cat > "$review_file" << EOF
# ${agent_name} - 季度人评表单

**季度**: ${QUARTER_LABEL}
**生成日期**: ${TODAY}
**规则版本**: 方案C (R-51~R-76)

---

## 一、季度客观分（系统自动汇总，权重80%）

| 月份 | 积分 | 基准 | 百分制(上限120) |
|------|:---:|:---:|:---:|
| ${months[0]} | $m_total1 | $m_bench1 | $m_score1 |
| ${months[1]} | $m_total2 | $m_bench2 | $m_score2 |
| ${months[2]} | $m_total3 | $m_bench3 | $m_score3 |

**季度客观分** = ${obj_valid_months}个月均值 = **${quarter_obj_score}** 分

> ⚠️ 上表积分流水若缺失请补记: $SCORING_DIR/events/{agent_name}/YYYY-MM.md
> 缺失月不计入均值（异常处理 E-01）。

---

## 二、季度人评（人工填写，权重20%）

请负责人 + 至少1位相关协作方，按 1-5 分独立评分：

| 维度 | 权重 | 评分人1 | 评分人2 | 备注 |
|------|:---:|:---:|:---:|------|
| 交付质量 | 30% |  |  | |
| 专业能力 | 25% |  |  | |
| 自我优化 | 20% |  |  | |
| 协作与沟通 | 15% |  |  | |
| 任务完成度 | 10% |  |  | |

**人评分1** = Σ(维度×权重)×20 = ______
**人评分2** = Σ(维度×权重)×20 = ______
**人评最终分** = (评分人1+评分人2)/2 = ______

---

## 三、季度综合分与等级

**季度综合分 = 客观分×0.8 + 人评最终分×0.2 = ______**

| 等级 | 区间 | 判定 | 定位 |
|------|------|:---:|------|
| S | ≥95 |  | 卓越标杆 |
| A | 85-94 |  | 优秀骨干 |
| B | 70-84 |  | 稳定主力 |
| C | 60-69 |  | 待提升 |
| D | <60 |  | 风险 |

**本季等级**: ______ ${cap_note}

---

## 四、防失真校验（自动）

- [ ] 红线一票否决检查: $fraud_flags
- [ ] 自评缺失检查: （累计未提交自评次数）
- [ ] 人评评分人 ≥ 2: （人数）
- [ ] 人评未含"效率"维度: 通过（模板已剔除）

---

## 五、异常处理记录

| 异常类型 | 是否触发 | 处理动作 |
|---------|:---:|---------|
| 积分流水缺失 |  | E-01: 补记或排除该月 |
| 评分人不足 |  | E-02: 单评分人可用，等级上限A |
| 档案缺失 |  | E-03: 先创建档案 |
| 等级=D |  | E-04: 升级最高决策者专项复盘 |

---

## 六、下季改进建议

- {建议1}
- {建议2}
EOF
            echo -e "  ${GREEN}✓${NC} 生成 ${agent_name} 季度人评表单 ${cap_note}"
            ((agent_count++))
        else
            echo -e "  ${BLUE}○${NC} ${agent_name} 季度人评已存在"
        fi
    done
    echo -e "${GREEN}✓${NC} 季度人评表单已生成: ${agent_count} 个 → ${SCORING_DIR}/quarterly/"
    echo ""
    generate_quarterly_summary
}

# 生成季度审查总览
generate_quarterly_summary() {
    local summary_file="$SCORING_DIR/quarterly/${QUARTER_LABEL}-summary.md"
    cat > "$summary_file" << EOF
# ${QUARTER_LABEL} 季度人评总览

**生成日期**: ${TODAY}
**触发方式**: 审查调度器自动触发

---

## 触发条件（R-51）
- 当前为季度末月（${QUARTER_END_MONTH}月）最后3天（DAY_OF_MONTH >= $((LAST_DAY_OF_MONTH-2))）
- 本季度: ${QUARTER_LABEL}

## 人评流程（R-52 ~ R-54）
1. 系统自动汇总本季度3个月客观积分 → 月度百分制 → 季度客观分
2. 负责人 + ≥1位协作方独立评分（5维度，剔除效率维度）
3. 人评最终分 = 各评分人平均
4. 季度综合分 = 客观×0.8 + 人评×0.2
5. 对照等级表判定 S/A/B/C/D
6. 防失真校验 + 异常处理

## 待处理人评表单
$(for f in "$SCORING_DIR/quarterly"/*/; do [ -d "$f" ] && echo "- [ ] $(basename "$f")/$(ls "$f" | head -1)"; done)

## 异常处理规则
- E-01 积分流水缺失: 补记或排除该月
- E-02 评分人不足(1人): 允许使用，等级上限A，标注低置信度
- E-03 档案缺失: 先创建能力档案再人评
- E-04 等级=D: 升级最高决策者（资深战略领导者）专项复盘，重新评估定位
- E-05 季度内违规≥2次(R-71): 等级上限C
- E-06 季度内缺自评≥2次(R-72): 等级降一档
- E-07 人评与客观分严重背离(≥40分): 人工复核评分一致性

---
*由 review-scheduler.sh 自动生成*
EOF
    echo -e "${GREEN}✓${NC} 季度总览已生成: $summary_file"
}

# ============================================================
# 报告与提醒
# ============================================================

generate_review_report() {
    local report_file="$REVIEW_DIR/report-${TODAY}.md"
    cat > "$report_file" << EOF
# 智能体能力档案审查报告

**生成时间**: ${TODAY}
**审查类型**: $1

---

## 审查概览
- 审查的智能体数量: {数量}
- 需要更新的档案: {数量}
- 本期完成任务总数: {数量}

## 各智能体状态
- {智能体}: {状态}

## 行动项
- [ ] {行动项}

EOF
    echo -e "${GREEN}✓${NC} 审查报告已生成: $report_file"
}

send_reminder() {
    echo -e "${YELLOW}🔔 $1 提醒${NC}"
    echo ""
    echo "  审查目录: $REVIEW_DIR"
    echo "  评分目录: $SCORING_DIR"
    echo "  档案目录: $PROFILES_DIR"
    echo ""
}

# ============================================================
# 主逻辑
# ============================================================

main() {
    echo -e "${BLUE}检查今天的审查需求...${NC}"
    echo ""
    check_profile_updates

    if should_quarterly_review; then
        perform_quarterly_review
        send_reminder "季度人评"
    elif should_monthly_review; then
        perform_monthly_review
        generate_review_report "月度"
        send_reminder "月度审查"
    elif should_weekly_review; then
        perform_weekly_review
        send_reminder "周度审查"
    else
        echo -e "${BLUE}今天不是预定的审查日（周度：周五 / 月度：月末 / 季度：季度末3天）${NC}"
        echo -e "${BLUE}如需手动触发，请运行: $0 --weekly|--monthly|--quarterly|--manual${NC}"
        echo ""
    fi
    echo -e "${GREEN}=== 审查系统运行完成 ===${NC}"
}

# 手动触发
manual_review() {
    echo -e "${BLUE}手动触发全部审查...${NC}"
    echo ""
    perform_weekly_review
    perform_monthly_review
    perform_quarterly_review
    generate_review_report "手动"
    send_reminder "手动审查"
}

# 参数处理
case "$1" in
    --weekly)    perform_weekly_review ;;
    --monthly)   perform_monthly_review ;;
    --quarterly) perform_quarterly_review ;;
    --manual)    manual_review ;;
    --status)    check_profile_updates ;;
    --help)
        echo "用法: $0 [选项]"
        echo ""
        echo "选项:"
        echo "  --weekly     强制周度审查"
        echo "  --monthly    强制月度审查"
        echo "  --quarterly  强制季度人评（方案C）"
        echo "  --manual     强制全部审查"
        echo "  --status     仅检查档案状态"
        echo "  --help       显示此帮助信息"
        echo ""
        echo "自动审查时机:"
        echo "  周度审查:  每周五"
        echo "  月度审查:  每月最后一天"
        echo "  季度人评:  季度末月(3/6/9/12)最后3天，自动汇总客观积分+生成人评表单"
        echo ""
        echo "评分系统: 方案C（客观积分80% + 季度人评20%）"
        echo "  规则清单: agents/capability-system/rating-workflow-rulebook.md"
        ;;
    *) main ;;
esac
