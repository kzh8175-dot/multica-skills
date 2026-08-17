# 智能看板 · 生产版（评分方案 C · 原型 B 落地）

> 归属：KA-96 智能看板研发立项（前端 + 数据可视化 + 真实数据接入）
> 基准：原型 B 修订版 v2（`dashboard-prototype-B.html`，浅色专业后台）
> 数据：评分方案 C 生产树 `<WORKSPACE>/prod/rating-system/` 真实数据（只读）

## 部署访问（Owner 直达）

看板已上线公网，**浏览器访问**：

```
http://43.108.86.63/
```

- **公网访问**：`http://43.108.86.63/`（阿里云首尔 · 24/7 在线 · 看板 8 页 + 明细下钻；HTTP 200 已验证）
- **本机生产树**：`/Users/kzh/multica_workspaces_desktop-api.multica.ai/e3ad92f3-ad8e-4eba-bce9-3e670bc345a3/prod/dashboard/index.html`（静态文件，浏览器直开）
- **路径**：`<WORKSPACE>/prod/dashboard/`（`<WORKSPACE>` = `/Users/kzh/multica_workspaces_desktop-api.multica.ai/e3ad92f3-ad8e-4eba-bce9-3e670bc345a3`）；服务器 `/opt/dashboard/`
- **8 页直达**：`#page-overview / #page-leaderboard / #page-trends / #page-detail / #page-events / #page-budget / #page-promotion / #page-escalation`
- **明细下钻**：`#page-detail?agent=agt-<slug>`（slug = category+名称 SHA-256 前 10 位）
- **部署记录 / 数据刷新**：`docs/DEPLOY.md` / `scripts/refresh-dashboard.sh`（定时每日 01:45 Asia/Shanghai）

## 交付物

| 文件 | 说明 |
|---|---|
| `index.html` | 生产看板 · 8 页（总览/排行榜/趋势/评分明细/事件流水/预算/升级队列/异常中心），数据驱动渲染 |
| `dashboard-data.js` | 真实数据（`window.DASHBOARD_DATA`），由生成脚本只读产出 |
| `dashboard-data-feed.py` | **团队标准数据接口**（KA-96 里程碑 1，仓库 `kzh8175-dot/multica-skills` commit `0093c62`，Schema v1.0 副本） |
| `generate-dashboard-data.py` | 数据接口层：调用 `dashboard-data-feed.build_feed()` → 映射为 `window.DASHBOARD_DATA` |
| `shots/*.png` | 8 页 + 明细页渲染截图（1440×1200 视口，供验收预览） |

## 使用

浏览器直接打开 `index.html`（与 `dashboard-data.js` 同目录）。侧边导航切换 8 页；支持 URL 直达
`#page-overview / leaderboard / trends / detail / events / budget / promotion / escalation`，
明细页携带参数 `#page-detail?agent=agt-<slug>` 直达单智能体视角（slug = category + 名称
SHA-256 前 10 位，跨重生成 / 跨季度稳定，不会因智能体增删而漂移）。

### 迭代 1（KA-98）功能完善

- **周期自适应**：`generate-dashboard-data.py` 不再硬编码 2026-Q3/2026-08，复用
  `dashboard-data-feed.current_month()/current_quarter()` 动态取当前月份/季度；季度月列表、
  人评窗口（季度末 3 天）、系统运行态事件时基全部随周期推导，重生成自动跟随；
- **事件流完整**：单行多事件（`R-21:自评;R-22:更新能力档案;R-23:协作`）按 `;` 拆分为独立
  事件行，积分按子事件均分，事件流页完整呈现 R-21/R-22/R-23；
- **深链稳定**：agent id 由 `agt-%03d`（位置序号）改为 `agt-<category+name 哈希>`，新增/
  重排智能体不影响既有深链；
- **按钮真实只读**：「预算对账」「处理待办」按钮由假动作改为真实只读校验 + 报告弹窗
  （`runReconcile()` 重算 spent/ceiling 与展示值比对；`runHandlePending()` 列出待处理
  数据缺口清单与处置路径），不再伪造成功提示。

### 数据刷新

生产数据每日结算 / 月末聚合后变化，重新生成数据文件即可：

```bash
python3 generate-dashboard-data.py \
  --prod-root <WORKSPACE>/prod/rating-system \
  --out dashboard-data.js
```

## 数据接口层（只读 · 团队标准）

`generate-dashboard-data.py` **消费团队标准接口** `dashboard-data-feed.py`（`build_feed()`，
Schema v1.0），页面前端**不再自行解析** `reviews/scoring` 下的 markdown —— 与开发者工具工程师
交付（commit `0093c62`）和数据工程师口径确认完全对齐：

- **类别（R-42）**：`multica agent list` `[category=X]` 标签 → 档案 category → 关键词推断；
- **R-41 月度百分制**：`clamp(月积分 ÷ 基准 × 100, 0, 120)`（整数除法）；
- **R-51 季度客观分**：`(7月+8月+9月 R-41) ÷ 3`（缺失月按 0 计并标 `E_MISS`）；
- **人评 / 综合 / 等级**：只读季度表单已回填值（`review_state=judged`）；当前 Q3 全部
  `pending`（窗口 09-28~09-30）→ 综合分/等级显示「待运行」，并携带 feed 提供的
  `estimated`（`basis=objective_only`）供「参考等级（预估）」标注场景使用；
- **防失真**：只读季度表单「四、」回填标记（R-71 / R-72 / E-02），看板不自算等级；
- **预算**：积分口径 = R-42 基准 × 季度3个月 × 智能体数（spent 取事件流水，余额 = ceiling−spent）；
  SOP 项目预算 = feed `budget.entries`（平台 issue metadata `budget.ceiling/spent/variance`，
  `variance = spent÷ceiling − 1`，>0 即超支）；
- **运行态**：feed `runtime`（结算/聚合/人评最近时基 + `rating.status` 计数）。

## 一致性保证

- **单一数据源**：8 页全部读取 `window.DASHBOARD_DATA`；`dashboard-data.js` 由
  `dashboard-data-feed.py` 一次聚合映射而来，跨页数值同源，无第二处口径；
- **与评分系统一致**：口径与聚合器 / 人评判定器 / 防失真层严格一致；
- **诚实呈现（试点期）**：仅「当月无事件流水」的智能体标 `E_MISS`（数据缺口）且不参与排名，
  避免「无数据 = 0 分 / D 级」误读；季度内部分月份缺失（Q3 试点期仅 8 月结算，7/9 月未到期）
  不误标为数据缺口——数据缺口口径见「已知边界」；综合分/等级按系统当前状态显示「待运行」，
  参考等级（预估）以 `est-tag` 标注、随季度人评转正式。

## 已知边界（如实声明）

- **数据缺口口径（KA-106 P1 修复）**：异常中心 / 事件流仅将「当月无事件流水」
  （`!hasData`）计为数据缺口；季度表单 `E_MISS` 是 R-51 对「季度内任意缺失月」计 0 的
  标记，Q3 试点期全员缺 7/9 月属未到期/待补记而非缺口——看板生成层只上抛 `!hasData`
  智能体（当前 39 个），24 个有 8 月真实数据的智能体不被误标「待处理」，跨页数据缺口数一致；
- 试点期数据稀疏且持续变动：智能体全集与有事件流水数随每日结算增长（生成时快照见
  `dashboard-data.js` 的 `meta`，含「试点初期·数据样本不足」时基标注）；
- 月度 R-41 为事件流水实时口径；生产月度报告文件可能早于最新事件，看板以事件流水 / feed 为准，
  与聚合器当前计算一致；
- 实时预览流（每 5 分钟刷新）尚未接入，事件流展示结算后的「入账终态」；
- 季度人评（R-52~55）与防失真最终判定待 Q3 人评窗口后由评审流程产出，看板届时重新生成数据文件即可自动反映。
