# 日更 autopilot 链路 SLO 守卫（KA-338 / A-3）

2026-09-11 · 系统稳定性工程师 · 来源：KA-336 人员配置会议行动项 A-3

## 1. 事件

2026-09-05 → 09-11，6 条日更 autopilot 链路 **34 次计划运行、20 次失败（58.8%）**，
且 **20 次全部静默**——不产生任何通知。直接后果：17+ 张日更 issue 滞留 `todo` /
`in_progress`、D24 门禁 SLA 日报断档 1 日、KA-314 每周预算对账失败、立项 SLA 超期
22 → 27。

## 2. SLO 规格

沿用 `runbook.md` §6 既有口径，不另起新指标：

| 项 | 定义 |
|---|---|
| **SLI-1 调度成功率** | 窗口内 `status ∈ {completed, issue_created}` 的 run 数 / 该窗口应执行的 run 数 |
| **SLI-2 落地率** | run 成功 **且** 对应 issue 进入 `in_review`/`done` 的比例（SLI-1 的派生，用于捕捉"run 成功但 agent 空转"） |
| **SLO-1** | SLI-1 ≥ **99%**（28 天滚动） |
| **SLO-2** | SLI-2 ≥ **95%** |
| **错误预算** | 6 链路 × 1 次/天 ≈ 180 次/月 → 1% ≈ **1.8 次失火/月** |
| **燃烧策略** | 28 天窗口内 ≥1 次**跨链路**失火（同日 ≥2 条链路失败）即触发 blameless 复盘——单链路偶发不触发 |
| **静默口径** | 应执行窗口过后仍无 run 记录 = 失败（沿用 runbook「静默 = 故障」），不计入"未监控"豁免 |

本周实测：34 计划 / 14 成功 = **41.2%**，错误预算消耗 ≈ 1000%（18 次超出预算）。

## 3. 根因占比表（本机侧 vs 平台侧）

判据：`multica autopilot runs <id> --output json` 的 `failure_reason`，逐条归类；
复现命令 `python3 scripts/autopilot-slo-guard.py --report --since 2026-09-05`。

| 侧 | 根因类别 | 次数 | 占比 | 判据 |
|---|---|---:|---:|---|
| 本机侧 | `local_runtime_unavailable` | 12 | 60.0% | `runtime unavailable while task was queued` ×11、`runtime went offline` ×1 |
| 本机侧 | `local_inference_gateway` | 7 | 35.0% | `API Error: 502 请求转发失败: 上游请求失败: client error (Connect)` |
| 本机侧 | `local_network_reset` | 1 | 5.0% | `start task failed: ... read tcp 198.18.0.2->198.18.0.49:443: connection reset by peer` |
| 平台侧 | — | **0** | **0.0%** | 窗口内真实 `上游 HTTP 502` 命中数 = 0 |
| | **合计** | **20** | **100%** | **本机侧 20/20** |

### 3.1 "上游 502" 不是平台侧故障（纠正 A-3 的初始归因）

A-3 把 7 次 `502` 记为"平台侧上游 502"。证据不支持这个归类：

1. **文案来源**：`请求转发失败: 上游请求失败: client error (Connect)` 是**本地推理网关
   cc-switch（`127.0.0.1:15721`）** 的 `[FWD-003]` 报文格式；错误文案本身也提示
   `check your inference gateway (127.0.0.1:15721)`。`ANTHROPIC_BASE_URL=http://127.0.0.1:15721`。
2. **网关日志**：`~/.cc-switch/logs/cc-switch.log` 在 09-04 → 09-07 区间记录 **238 条**
   `[FWD-003] Provider DeepSeek 请求失败: 请求转发失败: 上游请求失败: client error (Connect)`，
   每条前置 `TLS handshake failed: tls handshake eof`，并在 09-05 02:23:13 触发
   `[CB-004] 熔断器触发: 连续失败 8 次 → Open`。
3. **上游身份**：同日志 `请求目标: https://api.deepseek.com/anthropic/v1/messages`
   —— 上游是第三方模型服务，**不经过 Multica 平台**。
4. **平台侧反例为零**：同窗口 `上游 HTTP 502`（真实的平台/上游 5xx）命中数 = **0**。

**结论：7 次"502"是本机推理网关到上游模型服务的 TLS 连接失败，属本机侧。**
**未上报平台，也无需上报平台**——它不在平台的责任边界内。全仓 issue 检索
（`502` / `平台侧` / `上游`）无任何平台侧故障上报记录，与本结论一致。

### 3.2 runtime 不可用的物证：电源与休眠

`pmset -g log` 与失败日逐日对账：

| 日期 | Sleep 记录数 | 电源状态 | 当日运行结果 |
|---|---:|---|---|
| 09-05 | 166 | BATT 2–3% | 5/5 失败（推理网关 TLS） |
| 09-06 | 75 | BATT 1–2% | 5/5 失败（4 runtime + 1 网络 reset） |
| 09-07 | 0 | BATT 1%（休眠/关机） | 每日 5 条中 4 失败 + 预算对账失败 |
| 09-08 | 58 | AC 100% → BATT | **5/5 成功** |
| 09-09 | 28 | AC 100% → BATT 1% | 5/5 失败（含 `Low Power Sleep` 13572s + `Wake from Hibernate`） |
| 09-10 | 7 | AC 充电中 | **5/5 成功** |
| 09-11 | 1 | AC | **5/5 成功** |

失败日 = 电池供电 + 极低电量 + 低电量休眠；成功日 = 接入 AC 或电量充足。
这是 12 次 `runtime unavailable` 的直接机制。

## 4. 告警阈值方案（可执行）

当前链路失败**静默无通知**。落地方案：`scripts/autopilot-slo-guard.py --check --notify`，
建议每 15 分钟调度一次（`scripts/install-autopilot-slo-guard.sh`）。

| 规则 | 阈值 | 理由 |
|---|---|---|
| **R1 连续失败** | 任一链路连续 **3** 次失败 → P1 建单 | 单次失败可能是瞬时抖动；3 连败已越过"偶发"边界 |
| **R2 跨链路** | 同一自然日 **≥2** 条链路失败 → P1 建单 | 跨链路同时失火 = 系统性（电源/runtime/网关），不是脚本 bug |
| **R3 P0 时序链路** | 状态变更钩子（唯一位于下游结算 00:30 之前的链路）**单次**失败即 P1 | 补偿窗口仅 9 分钟，等 3 次已错过 3 天入账 |
| **R4 静默漏跑** | 槽位 + 30 min 仍无 run 记录 → 视同失败，参与 R1/R2 | 「静默 = 故障」（runbook §3） |
| **去重** | 同 `(链路, 根因类别)` **24h** 内只建单一次 | 一次电源事故会连挂 5 条链路，不去重会刷 5 张单 |
| **升级** | P1 单 24h 未处置 → 资深战略领导者（SLA 48h） | 沿用 runbook §3 既有路径 |
| **不告警** | 单链路单次失败且当日其他链路正常 | 记入周报观察，不制造噪音（告警按用户可见影响，不按错误字符串） |

**回放验证**（`SLO_GUARD_NOW` 冻结时钟，逐日回放）：

| 假装此刻 | 判定 |
|---|---|
| 09-05 23:00 | 🔴 R3 钩子 + R2 跨链路 5 条 |
| 09-06 23:00 | 🔴 R3 钩子 + R2 跨链路 5 条 |
| 09-07 23:00 | 🔴 R1 ×4 链路 3 连败 + R2 跨链路 5 条 |
| 09-08 23:00 | ✅ 无告警 |
| 09-09 23:00 | 🔴 R2 跨链路 2 条 |
| 09-10 23:00 | 🔴 R3 钩子 + R2 跨链路 3 条 |
| 09-11 09:40 | ✅ 无告警 |

即：**首个失火日（09-05）就会建单**，而不是一周后靠人翻日志发现；干净日零误报。

## 5. 失火后追偿口径

### 5.1 两条通道，绝不重复建单

关键事实：**FAILED run 已经建过 issue**（实测 `run.issue_id` 非空，例如 09-09 钩子
失败 run → KA-328 滞留 `todo`）。因此：

| 情形 | 追偿动作 | 禁止动作 |
|---|---|---|
| **MISSED**（平台无 run 记录、未建 issue） | `multica autopilot trigger <autopilot_id>` | — |
| **FAILED**（有 run、有滞留 issue） | 对**既有 issue** 就地补跑：`multica issue assign <issue_id> --to-id <agent>` | ❌ `autopilot trigger`（会生成第二张同名 issue，KA-328 已实证） |

`--compensate` 三条模式：`off` / `report`（默认，只输出补跑命令）/ `assign`（自动补跑）。
默认 `report` 是有意保守：自动补跑会消耗 agent 运行配额，开关交给 owner 拍板。

### 5.2 退避与截止（尊重时序）

- 抖动退避：`45s × 2^n`，抖动 ±30%，最多 3 次。
- **硬截止**：每个链路声明 `deadline`（钩子 = 00:29）。重试过程中撞上截止立即停止。
  这是必须的——钩子必须早于结算 00:30，窗口只有 9 分钟；如果无脑退避到 00:40，
  补跑出来的变更也无法当日入账。过期不追偿，转告警通道。

### 5.3 漏跑窗口内状态变更不丢（复用既有机制，不另起）

三层保证，全部复用 KA-333 / KA-334 已有经验：

1. **L1 幂等重跑**（复用 runbook §4）：所有包装脚本幂等——结算器按 `pending→credited`
   状态机流转，已 credited 触发 `E_DUP` 跳过；聚合器是事件流水的纯函数；人评有
   `[ ! -f ]` 守卫。补跑不会双计。
2. **L2 状态跟踪追偿**（复用 KA-333 的 `rating.last_status`）：钩子以状态为水位，
   漏跑次日运行时会重新比对当前状态并补写。KA-333 已实证 09-10 漏跑当日 **0 事件丢失**。
3. **L3 残留盲区修补**（本次新增提案，补 KA-333 指出的 A→B→A 回摆）：
   `last_status` 只存状态，issue 在两次运行之间发生 `done → in_progress → done`
   回摆时首尾相等 → 报 `no-transition`，该往返的 R-04（退回返工）静默丢失。
   **修法**：钩子同时记录处理时刻的 `rating.last_seen_updated_at`（issue `updated_at` 水位）。
   每次运行时若 `issue.updated_at > rating.last_seen_updated_at` 且 `status == rating.last_status`
   → 判定为**疑似状态回摆**，写入当日 hook 日志与周报观察项，不再静默。
   只加一个已存在的字段，不改状态机、不影响幂等，可先用 `--dry-run` 观察一周再放开。

### 5.4 生产树前置自愈（复用 KA-334）

`prod/` 会周期性整体缺失（已复现 6 次）。追偿前先跑
`bash scripts/ensure-prod-tree.sh`，把"重建"变成确定性步骤；`MULTICA_HTTP_TIMEOUT=60`
已按 KA-333 经验**固化进 4 个包装脚本**（`scripts/run-*.sh`），不再依赖事后定向重跑。

## 6. 本机侧缓解措施

| 措施 | 落地物 | 复验 |
|---|---|---|
| 窗口保活（对治 12 次 runtime 不可用） | `scripts/schedule-keepawake.sh` | 实跑：启动 → 幂等 no-op → `--status` → `--stop` 全通；高风险分支 rc=1 已验证 |
| 电源体检与显式告警 | 同上 `--preflight` | 电池供电且 <25% 时输出"低电量休眠将吞掉本窗口"并 rc=1 |
| 失败告警（对治"静默"） | `scripts/autopilot-slo-guard.py --check --notify` | 逐日回放：每个失火日都建单、干净日零误报 |
| 漏跑/失败追偿 | 同上 `--compensate` | dry-run 复原出本周 **20 张滞留 issue 的确切 id 与就地补跑命令** |
| 超时前置（复用 KA-333） | `scripts/run-*.sh` 内置 `MULTICA_HTTP_TIMEOUT=60` | `bash -n` 语法校验通过 |
| 配置漂移防护 | `--sync-schedule` | 从 `multica autopilot get` 回读 6 条 cron/时区/指派；二次运行 0 变更（幂等） |
| 常驻调度 | `scripts/install-autopilot-slo-guard.sh` | 4 个 LaunchAgent plist 全部通过 `plutil -lint`（**未加载**） |

### 6.1 保活做不到的部分（必须 owner 决策）

`caffeinate` **拦不住**电池耗尽时的 `Low Power Sleep` / hibernate——09-09 那次 13572s
休眠就是硬件保护。软件层只能做到"电量充足时保活 + 电量低时显式告警"。
若无法在调度窗口内常接 AC，需 owner 评估：

```bash
# 关闭电池模式下的待机休眠（需要 sudo，影响续航/发热，请自行权衡）
sudo pmset -b standby 0 hibernatemode 0
```

### 6.2 启用常驻调度（需 owner 确认）

```bash
cd <repo>
bash scripts/install-autopilot-slo-guard.sh            # 已生成，未加载
bash scripts/install-autopilot-slo-guard.sh --load     # 加载（会改变本机电源行为）
bash scripts/install-autopilot-slo-guard.sh --unload   # 回滚
```

## 7. 日常操作

```bash
# SLO / 根因占比报告
python3 scripts/autopilot-slo-guard.py --report --since 2026-09-05

# 告警判定（只判定）
python3 scripts/autopilot-slo-guard.py --check
# 判定并建单
python3 scripts/autopilot-slo-guard.py --check --notify

# 追偿预演 / 执行
python3 scripts/autopilot-slo-guard.py --compensate --dry-run
python3 scripts/autopilot-slo-guard.py --compensate

# 配置漂移同步
python3 scripts/autopilot-slo-guard.py --sync-schedule

# 单元测试
python3 src/test-autopilot-slo-guard.py        # 43/43

# 状态文件（告警冷却 / 追偿记录）
cat ~/.multica/autopilot-slo-guard.state.json
```

## 8. 复盘触发条件

按 runbook §6：**当月 ≥1 次跨链路失火即触发 blameless 复盘**。本周满足条件，
复盘输入即本文件的 §3 占比表 + §4 回放结果 + `~/.cc-switch/logs/cc-switch.log`
与 `pmset -g log` 的原始证据。

---

*由 系统稳定性工程师 部署维护 · KA-338 / A-3*
