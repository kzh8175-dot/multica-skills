# 智能看板 · 生产部署记录（KA-104）

> 部署人：DevOps自动化工程师 · 日期：2026-08-17
> 归属：KA-102 联调验收与上线（里程碑 3）· 子任务 KA-104

## 部署路径

```
<WORKSPACE>/prod/dashboard/
  index.html                  8 页看板（总览/排行榜/趋势/评分明细/事件流水/预算/升级队列/异常中心）
  dashboard-data.js           window.DASHBOARD_DATA（生成于 2026-08-17T07:30Z，生产数据实跑）
  generate-dashboard-data.py  数据接口层（消费 dashboard-data-feed.py → 映射看板数据）
  dashboard-data-feed.py      团队标准只读数据接口（multica-skills @ b64cb64，Schema v1.0）
  README.md                   交付说明（前端工程师）
  crontab-dashboard.conf      看板数据刷新定时任务配置
  scripts/refresh-dashboard.sh 数据刷新包装脚本（幂等 + 日志 + 失败退出码）
  logs/dashboard/             刷新日志（YYYY-MM-DD.log）
```

`<WORKSPACE>` = `/Users/kzh/multica_workspaces_desktop-api.multica.ai/e3ad92f3-ad8e-4eba-bce9-3e670bc345a3`
（与 `prod/rating-system` 同级）

## 访问方式

浏览器直接打开 `<WORKSPACE>/prod/dashboard/index.html`（静态文件，无服务依赖；
`dashboard-data.js` 与 `index.html` 同目录）。

- 侧边导航切换 8 页；
- URL 直达：`#page-overview / #page-leaderboard / #page-trends / #page-detail /
  #page-events / #page-budget / #page-promotion / #page-escalation`；
- 明细下钻：`#page-detail?agent=agt-<slug>`（slug = category+名称 SHA-256 前 10 位，跨重生成稳定）。

## 数据刷新

```bash
<WORKSPACE>/prod/dashboard/scripts/refresh-dashboard.sh
```

- 幂等：生成器确定性（feed 只读 + 同输入同输出），重复运行仅刷新 generatedAt / 实时运行态；
- 口径：与评分系统同源（月度 R-41 / 季度 R-51 / 等级 / 预算 / 事件流水）；
- 覆盖：每日结算 / 月末聚合 / 季度人评（Q3 窗口 09-28~09-30）/ 每周预算对账 自动反映；
- 定时：`crontab-dashboard.conf`（每日 01:45 Asia/Shanghai，晚于结算 00:30 与聚合 01:15），
  待接入 Multica autopilot schedule trigger。

### 退出码与降级（KA-456 · 2026-09-28）

2026-09-27 刷新 run（KA-446）实测发现：`dashboard-data-feed.py` 以 `--limit 200` 调用
`multica issue list`，而 CLI 硬上限为 100 ⇒ 首页即 `rc=1` ⇒ `budget.sop` 与
`runtime.ratingStatus` **两张表同时恒空**，而任务 `exit=0`、日志全 `✓`、无告警，
该状态已持续约两周未被发现。修复后：

- `exit=0`：读数完整；
- `exit=3`：**读数降级**（CLI 不可用 / 分页中途失败 / 参数契约破裂）。产物仍落盘并带
  `meta.degraded` 标记（`any/mode/items/failed_reads`），日志打 `⚠ 降级` 与
  `⚠ 预算` / `⚠ 升级队列`；调度侧 L1 告警应按**输入可用性**归因（沿用评分系统
  runbook §3 KA-356 分轨），不是脚本逻辑故障；
- `exit=2`：生成器自身故障（feed 脚本缺失等）→ P1。

验证（2026-09-28，非破坏性：在 `prod/dashboard` 的临时副本上跑，未改动生产文件）：

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| 真 CLI 正常 | `SOP 行 0` / `ratingStatus {}` / exit 0 | `SOP 行 7` / `pending 4 · escalated 0 · credited 283` / exit 0 |
| CLI 不可用 | 全 `✓` / exit 0 | `⚠ 降级` 三项 / exit 3 |

`meta.degraded` 使「读取失败」与「真的为空」在产物中可区分——这正是该缺陷潜伏两周的直接原因。

## 访问验证（2026-08-17）

| 页 | 直达锚点 | 数据源字段 | 验证 |
|---|---|---|---|
| 总览 | `#page-overview` | `meta` / `monthly` / `quarterly` / `runtime` | ✅ |
| 排行榜 | `#page-leaderboard` | `agents` + `quarterly` | ✅ |
| 趋势 | `#page-trends` | `monthly[各月]` | ✅ |
| 评分明细 | `#page-detail` | `quarterly` 单 agent 全字段 | ✅ |
| 事件流水 | `#page-events` | `events` | ✅ |
| 预算 | `#page-budget` | `budget.entries` / `budget.points` | ✅ |
| 升级队列 | `#page-promotion` | `agents.category` + `quarterly.grade` | ✅ |
| 异常中心 | `#page-escalation` | `runtime.rating_status` + `flags` | ✅ |

生成口径：63 智能体 / 24 有数据 / 141 事件 / 预算 ceiling 66300 spent 375 / 7 SOP 行 /
结算 2026-08-17T04:57Z · 聚合 04:57Z · 人评 04:58Z（Q3 待运行，09-28~09-30 窗口）。

## 数据一致性（feed 重生成验证）

1. 首次生成（部署）：`dashboard-data.js` generatedAt `2026-08-17T07:30:56Z`；
2. 重生成（刷新验证）：再次运行 `refresh-dashboard.sh`，与首次输出结构/数值全量一致
   （仅 generatedAt 与实时运行态计数按预期变化），与评分系统数据抽查一致。

## HTTP 访问服务（KA-108 部署接线 · 2026-08-17）

- **访问 URL**: `http://localhost:8080/index.html`（8 页锚点直达；远程经 SSH 隧道 `ssh -L 8080:localhost:8080 <user>@<host>`）
- **服务**: launchd `com.multica.dashboard.http`（python3 http.server，绑定 127.0.0.1，KeepAlive 保活）
- **日志**: `logs/http-server.log` / `logs/http-server.err.log`
- **停止/启动**:
  ```bash
  launchctl bootout   gui/$(id -u) ~/Library/LaunchAgents/com.multica.dashboard.http.plist
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.multica.dashboard.http.plist
  ```
- **数据刷新 autopilot**: `7151602b-0778-4d7b-bc65-1008a8bfaafa`（每日 01:45 Asia/Shanghai，schedule trigger `1f06c1ab-8eb4-4ccb-a98f-b30ca0e8f225`）→ 运行 `scripts/refresh-dashboard.sh`

## 生产树自愈（KA-334 · 2026-09-11）

workspace 级 `<WORKSPACE>/prod/` **整体缺失已是复现 6 次的常态故障**
（KA-213 / KA-223 / KA-254 / KA-277 / KA-318 / KA-334）。缺失时
`prod/dashboard/scripts/refresh-dashboard.sh` 不存在 → 每日 01:45 刷新任务
直接失败；同时 launchd `com.multica.dashboard.http` 仍在跑，`http://localhost:8080/`
回落为目录列表（首页 404）——**静默降级，无报文**。

自愈脚本 `scripts/ensure-prod-tree.sh` 把「重建」从人工步骤变成确定性步骤：

```bash
PROD_ROOT=<WORKSPACE>/prod bash scripts/ensure-prod-tree.sh   # exit 0=健康（含刚重建）
```

- **判据**：`dashboard/{index.html, generate-dashboard-data.py, dashboard-data-feed.py, scripts/refresh-dashboard.sh}` 齐备 且 `rating-system/agents/` 存在；
- **幂等**：健康时 no-op（只打印，不写文件），复跑无需清理；
- **保留日志**：重建 dashboard 不触碰 `logs/`，历史刷新日志与 bootstrap 日志不丢；
- **只读平台**：只从 git 远端拉取，不读写 Multica 平台数据；
- **失败显式**：任一环节失败退出码非 0，由调度 agent 按 runbook 告警。

调度接线（runbook 口径）：每日 01:45 任务**先** `ensure-prod-tree.sh`，**再** `refresh-dashboard.sh`；
两者都幂等，串行执行安全。

### 已知边界

- 自愈从 **git main** 物化，roster 以上游 main 为准。若 main 落后于平台活跃智能体
  （如 KA-325 的 5 建档 + 1 更名合并尚未入库），自愈后看板智能体数会低于昨日常态
  ——这是**上游缺档**，需由「智能体同步」任务 + GitHub 仓库管理员入库闭合，本脚本不代偿。
- 自愈不覆盖 `rating-system` 的本地增量（自愈只在缺失时触发；已存在的树不会被覆盖或重置）。
