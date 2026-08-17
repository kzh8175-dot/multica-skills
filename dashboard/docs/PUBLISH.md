# 看板发布流程 · 本地刷新 → 自动同步公网 + 一致性校验

> 版本：v1.0（2026-08-17）· 归属：KA-102 里程碑 3 运维增强
> 目标：`refresh-dashboard.sh` 刷新本地后，公网 `http://43.108.86.63/dashboard-data.js` 不再静默滞后。

## 一、背景与约束（为什么今天会"不同步"）

- **现状**：本地生产树是数据源（`refresh-dashboard.sh` → `dashboard-data.js`）；公网服务器为静态文件服务，**无自动同步通道**——本轮"未知智能体 15 分"修复后，本地已清、公网仍是旧文件，正是缺校验导致的静默滞后。
- **约束**：自动化环境网络仅放行 HTTP/HTTPS（无法 SSH）；公网服务器无上传/管理端点（/upload、/admin 均 404）。
- **结论**：全自动推送需要一次性给公网服务器配置上传通道（见 §四）；在此之前采用「**半自动 + 强校验**」——本地自动出包 + 服务器一条命令应用 + 自动校验，任何不同步都会被**显式 FAIL** 而不是静默。

## 二、发布流程（当前可落地 · 半自动）

```
┌────────────── 本地（自动） ──────────────┐   ┌────── 公网服务器（Workbench 一次）──────┐
│ publish-dashboard.sh prepare            │   │                                        │
│  ① refresh-dashboard.sh 刷新本地        │   │ 上传 新 dashboard-data.js              │
│  ② 生成 dashboard-manifest.json         │   │ + dashboard-manifest.json 到服务器     │
│   （sha256 + generatedAt + 内容指纹）    │──▶│                                        │
│ ③（可选）DASH_PUSH_URL 配置则 curl 推送 │   │ bash apply-verify-server.sh            │
│ ④ publish-dashboard.sh verify           │◀──│  覆盖文件 + 就地校验 SHA256/时间/指纹    │
│    拉取公网比对 → PASS / FAIL           │   │                                        │
└─────────────────────────────────────────┘   └────────────────────────────────────────┘
```

- **日常单条命令**：`publish-dashboard.sh all`（prepare → push(如有) → verify）
- **未配置推送时**：`verify` 会 FAIL 并提示执行 `apply-verify-server.sh`，杜绝"以为同步了其实没有"。

## 三、一致性校验方法论（三个层次，任一不通过即 FAIL）

### 1. 整文件级：SHA256
- `dashboard-manifest.json.sha256` = 本地 `dashboard-data.js` 字节级摘要；`verify` 对公网拉取的文件重算 SHA256 比对。
- **能抓**：任何字节差异（哪怕一个字段改动）；**抓不到**：人为篡改 hash（本流程内不存在）。

### 2. 数据生成级：generatedAt
- 解析 `meta.generatedAt`（UTC ISO8601）对比。文件每次刷新必变，若公网时间戳 ≠ 本地，说明公网是旧代次。
- **能抓**：内容相同但生成代次不同的"旧快照"（本次 10:17 vs 13:15 即此场景）。

### 3. 业务内容级：结构指纹（防"时间戳相同但内容被手改"）
- 指纹字段：`agents` 数 / `agentsWithData` / `events` 数 / `未知智能体` 计数 / 资深战略领导者 `monthTotal`/`monthPct`/`objective`。
- **能抓**：人工或异常把 15 分改错位、未知智能体复活、榜单数值漂移等。

> 三层次意义：SHA256=防任何改动；generatedAt=防旧快照；指纹=业务语义兜底。**三合一，任何一层不过都退出码非 0**，可接入 CI/告警。

### 校验退出码
| 码 | 含义 | 处置 |
|---|---|---|
| 0 | 完全一致 | 发布完成 |
| 2 | 公网未同步（差异） | 执行 apply-verify-server.sh 后重跑 verify |
| 非0 | 刷新/推送/网络失败 | 按日志排查 |

## 四、全自动化路径（可选升级，需一次性服务器配置）

### 路径 A：服务器加「带 token 的 HTTP PUT 上传端点」（推荐）
- 在服务器 dashboard 目录加一个最小端点（如 Python `http.server` 子类或 nginx `dav_methods`），校验 `X-Sync-Token` 后落盘。
- 本地：`export DASH_PUSH_URL=http://43.108.86.63/upload/dashboard-data.js DASH_PUSH_TOKEN=<token>` → `publish-dashboard.sh all` 即**全自动推送 + 自动校验**。
- 安全：token 不写死在脚本（环境变量/密钥文件），端点仅接受 dashboard-data.js 白名单路径，落盘前校验 JSON 结构。

### 路径 B：公网服务器 cron 从仓库/Release 拉取
- 把 `dashboard-data.js` 随每次发布提交到 multica-skills 仓库；服务器 cron 定时 `git pull` / 下载 Release 资产并覆盖。
- 前提：服务器可访问 GitHub；验收同 §三。

### 推荐节奏
先按 §二 半自动跑稳（本轮即用），**下次需 Workbench 操作时顺手把路径 A 端点配上**，之后本地一条 `publish-dashboard.sh all` 全自动。

## 五、回滚

- 服务器侧 `apply-verify-server.sh` 每次覆盖前自动备份 `dashboard-data.js.bak-<时间戳>`；需回滚时把备份拷回并重跑校验。
- 本地 `dashboard-manifest.json` 保留上一代 sha256，可从 git 历史取旧文件。

## 六、相关文件

| 文件 | 作用 |
|---|---|
| `scripts/publish-dashboard.sh` | 本地侧：refresh → manifest → push(可选) → verify |
| `scripts/apply-verify-server.sh` | 服务器侧：覆盖 + 就地校验（Workbench 执行）|
| `dashboard-manifest.json` | 发布指纹清单（sha256 / generatedAt / 内容指纹）|

## 七、落地清单（下一步）

- [ ] 本轮：用 `publish-dashboard.sh verify` 确认公网为 FAIL（旧数据）→ Workbench 上传新文件 → 重跑 verify 转 PASS
- [ ] 将本脚本 + 文档提交到 multica-skills 仓库（仓库==生产）
- [ ] 全自动路径 A 一次性配置（下次 Workbench 时）
