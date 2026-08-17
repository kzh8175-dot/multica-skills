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
