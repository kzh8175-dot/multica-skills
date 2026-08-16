# 岗位 × 技能 白名单与禁配规则（skill-whitelist）

> **版本**：1.0.0 · **制定**：资深战略领导者 · **日期**：2026-08-17
> **用途**：定义工作区岗位类别与技能类型的匹配规则，确保「岗位与技能不错配」，新增智能体/技能时可复用。

## 目录结构

```
config/skill-whitelist/
├── whitelist.py               # 规则引擎（岗位映射 + 技能分类 + 白名单 + 禁配 + 校验入口）
├── skill-whitelist-rule.md    # 规则文档（白名单矩阵 / 禁配规则 / 应用说明 / 维护建议）
└── README.md                  # 本说明（使用指南 / 版本 / 维护入口）
```

## 使用说明

### 1. 校验当前全部 agent 技能绑定

```bash
# 生成 agent→技能 映射 JSON
python3 - <<'EOF'
import json, subprocess
agents = json.loads(subprocess.run(["multica","agent","list","--output","json"],capture_output=True,text=True).stdout)
out = {}
for a in agents:
    r = subprocess.run(["multica","agent","skills","list",a["id"],"--output","json"],capture_output=True,text=True).stdout
    d = json.loads(r); items = d if isinstance(d,list) else d.get("skills",[])
    out[a["name"]] = [s.get("name","") if isinstance(s,dict) else str(s) for s in items]
json.dump(out, open("/tmp/agents-skills.json","w"), ensure_ascii=False, indent=1)
EOF

# 运行规则校验
python3 config/skill-whitelist/whitelist.py --verify --agents-file /tmp/agents-skills.json
# → ✅ 全部 N 个 agent 技能绑定合规  或  ⚠️ 列出违规项
```

### 2. 新增智能体时

1. 按岗位职责归入 7 类岗位之一（`ROLE_MAP`）；
2. 套用 `ALLOWED[role]` 白名单分配技能；禁配类型（`FORBIDDEN[role]`）一律不绑定；
3. 用 `verify_agent_skills()` 校验后落地。

### 3. 新增技能时

1. 先归入 `SKILL_TYPE` 中某个/多个类型（在 `whitelist.py` 中登记）；
2. 据此确定可绑定的岗位类别（该类型 ∈ 岗位的 `ALLOWED` 且 ∉ `FORBIDDEN`）；
3. 避免无约束扩散绑定。

### 4. 作为模块引用

```python
import sys
sys.path.insert(0, 'config/skill-whitelist')
from whitelist import ROLE_MAP, SKILL2TYPE, ALLOWED, FORBIDDEN, is_allowed, verify_agent_skills

is_allowed('FIN', '系统性调试')            # → False
verify_agent_skills(agent_skills_map)      # → 违规列表
```

## 规则摘要

| 维度 | 内容 |
|---|---|
| 岗位类别 | MGMT 管理 / FIN 财务 / SVC 客服销售培训 / CONTENT 内容营销 / DESIGN 设计创意 / DATA 数据研究 / ENG 工程技术 |
| 技能类型 | BASE 底座 / DEV_CORE 核心开发 / DEV_REV 代码审查 / DEV_DEPLOY 部署运维 / DEV_DESIGN 设计工程 / SEC 安全治理 / PLAN 规划管理 / DESIGN_CR 创意设计 / WRITE 内容写作 / IMAGE 图像生成 / RESEARCH 调研采集 / COACH 教学沟通 |
| 白名单 | `ALLOWED[role]`：ENG 全量；DATA 全量（含安全/图像）；DESIGN/CONTENT 禁开发部署安全；MGMT 禁开发部署安全但含评审；FIN/SVC 最小集 |
| 禁配 | `FORBIDDEN[role]`：FIN/SVC/DESIGN/CONTENT/MGMT 明确禁 DEV_CORE/DEV_DEPLOY/SEC 等 |
| 身份技能 | agent 绑定同名 persona 技能不受规则约束，始终保留 |

## 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| 1.0.0 | 2026-08-17 | 初始版本。已应用到全部 69 个智能体（1420 绑定，0 违规）。分类要点：并行派发子代理归 PLAN；图像/安全放宽到数据/文档/培训/售前岗 |

## 维护入口

- **规则变更**：编辑 `config/skill-whitelist/whitelist.py`（`SKILL_TYPE` / `ALLOWED` / `FORBIDDEN`）并同步更新 `skill-whitelist-rule.md`，版本号 +1；
- **周期性核查**：建议每月运行一次 `--verify`（可挂入 cron/autopilot）；
- **责任人**：资深战略领导者（规则 owner），变更需 owner 审批。
