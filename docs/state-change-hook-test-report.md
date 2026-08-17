# state-change-hook.py 验收测试报告（P2-11 / KA-76）

**任务**: KA-76 P2-11 状态变更钩子（完成/失败/返工自动写事件）
**执行人**: 开发者工具工程师
**日期**: 2026-08-17
**脚本**: `agents/capability-system/state-change-hook.py`（仓库 `src/state-change-hook.py`）
**测试**: `agents/capability-system/tests/test-state-change-hook.py`（仓库 `src/test-state-change-hook.py`）

---

## 一、交付物

| 文件 | 说明 |
|---|---|
| `state-change-hook.py` | 状态变更钩子（Python3；纯函数 `map_transition`/`classify_completion`/`skip_reason`/`decide` + CLI `--dry-run`/`--issue`/`--baseline`/`--no-auto-baseline`/`--json`） |
| `test-state-change-hook.py` | 验收测试套件（unittest，**56** 条用例全通过；含 12 条 main() 集成测试） |
| `run-state-change-hook.sh` | 定时任务包装脚本（守卫 + 日志 + 退出码，`logs/hook/YYYY-MM-DD.log`） |
| `crontab-rating.conf`（修改） | 新增第 0 项「状态变更钩子」cron 说明（每日 00:20，先于 00:30 结算） |

> 生产环境脚本位于 `agents/capability-system/`，本仓库镜像于 `src/`（与 P1-9/P1-10 同约定）。

## 二、职责与事件映射

状态变更钩子检测任务状态发生 完成/失败/返工 变更时，自动写入对应积分事件，与结算器
（`rating-settler.py`）/事件流水打通：

```
[状态变更] state-change-hook.py 检测 transition
   → 写 5 键 metadata（rating.status=pending，按 reviewer-guide §3.1 模板）
[每日结算] rating-settler.py → 事件流水 events/{agent}/YYYY-MM.md（(issue,事件) 去重）
[月末聚合] rating-aggregator.py → 月度百分制 / 季度客观分
```

| 状态变更 | 事件 | 积分 | 判定 |
|---------|------|:---:|------|
| → done（按时） | R-01 任务按时完成 | **+20** | 无 due_date 或完成日期 ≤ due_date（当天完成计按时） |
| → done（超时） | R-02 任务超时完成 | **+10** | 完成日期 > due_date |
| → cancelled | R-03 任务未完成/失败 | **-15** | from=done 的取消不重复记失败（防双计） |
| done/in_review → todo/in_progress | R-04 任务被退回返工 | **-10** | 退回返工 |

> 仅自动写 R-01~R-04 **确定性状态事件**；R-11~R-13 / R-31~R-33 需人评判定，钩子不写。

## 三、验收标准核对

| # | 验收标准 | 结果 |
|---|---------|------|
| 1 | 事件映射：done→R-01/R-02（按时/超时）、cancelled→R-03、返工→R-04；非评分 transition 不写事件 | ✅ 13 条用例 |
| 2 | 按时/超时判定：无 due→按时、当天完成→按时、超期→超时 | ✅ 5 条用例 |
| 3 | 跳过/延后逻辑：pending 延后、escalated 跳过、同事件已入账跳过、不同事件允许写入 | ✅ 5 条用例 |
| 4 | 事件 metadata：5 键齐备、trigger=reviewer、points 整数且类型为 number | ✅ 2 条用例 |
| 5 | 决策流：自动 baseline、no-transition、non-scoring、event-written、deferred、escalated、credited-same-event、测试数据隔离 | ✅ 13 条用例 |
| 6 | 写路径：注入 write 回调验证 6 次写入（5 键事件 + last_status）、dry-run 零写入、写失败报 write-error | ✅ 4 条用例 |
| 7 | main() 集成：baseline→transition→event→幂等全生命周期、返工检测、baseline 模式（含缺 baseline 写路径 + dry-run）、退出码契约（write/read-error→exit 1、无错误→exit 0）、dry-run、非 agent issue 过滤、纯 JSON 输出 | ✅ 12 条用例 |
| 8 | 真实数据 dry-run：83 个 agent 分配 issue → 80 建 baseline + 3 测试数据跳过，0 事件误写 | ✅ 实测 |
| 9 | KA-100 缺陷修复回归：`--baseline` 缺 baseline 真实写入 `rating.last_status`；写失败/读失败退出码=1、无错误退出码=0（cron 告警契约） | ✅ 6 条新增用例 |

**回归**：聚合器 15 / 结算器 11 / 人评判定 24 / 防失真 24 / 看板数据接口 35 / 状态变更钩子 56
（**165 条 Python**）+ 调度器 category 4 + 防失真集成 4（**8 项 bash**）全通过。

## 四、幂等与安全设计

| 维度 | 实现 |
|------|------|
| 状态跟踪 | 每个 issue 的 `rating.last_status` 记录上次处理的 status；无变更 → no-op |
| 首次运行 | 自动建立 baseline（只记录 status，不写事件），存量 done/cancelled **不触发**；`--baseline` 可显式全量建基线 |
| pending 保护 | 已有 `rating.status=pending` 的 issue **延后**（不覆盖，待其结算后补写；保留 `rating.transitioned_at`） |
| credited 保护 | 同事件已入账 → 跳过（结算器 E_DUP 兜底，防双计）；不同事件允许写入（新事件，旧事件保留在流水） |
| escalated 保护 | 已 escalated → 跳过并报告（不改写，升级人工处置） |
| 测试数据隔离 | `rating.test=true` → 跳过（与结算器口径一致） |
| 权限边界 | R-01~R-04 为行为类事件，按 reviewer-guide §3.1 以 `trigger=reviewer` 写入；本钩子为 P2-11 授权的确定性系统自动化，非智能体自我登记；已 credited/escalated 不改写事件值 |
| 可重跑 | 幂等 + `--dry-run` 只读预演；写失败报错不中断，可重跑 |

## 五、运行方式

```bash
python3 agents/capability-system/state-change-hook.py --dry-run    # 预演（推荐先跑）
python3 agents/capability-system/state-change-hook.py              # 正常扫描（自动建 baseline + 检测变更）
python3 agents/capability-system/state-change-hook.py --issue <id> # 单 issue（状态变更后直接调用）
bash scripts/run-state-change-hook.sh                              # 定时任务包装（日志 + 退出码）
```

> 首次上线：先 `--dry-run` 预览 → 正常跑一轮建立 baseline → 后续每日 00:20 cron 自动检测。
> cron 接线（autopilot 配置）属 P2-12 端到端跑通范畴，由 DevOps 按 `crontab-rating.conf` 第 0 项部署。

## 六、KA-100 缺陷修复记录（P2-12 部署接线前）

代码审查员验收发现的非阻塞项 1、2，已在 P2-12 部署接线前修复：

### 修复 1 · `--baseline` 模式静默空操作（中）
- **缺陷**：`main()` baseline 分支内联构造的 plan 含 `updates=[("rating.last_status", ...)]` 但从未应用（写路径只在 `process_issue` 内）；缺 baseline 的 issue 报告「建立 baseline」但**零写入**；`test_main_baseline_flag_only_records_missing` 只覆盖「已有 baseline」分支。
- **修复**：抽出 `_apply_updates(issue, plan, dry_run, write)` 作为统一写路径，`process_issue` 与 baseline 分支共用；baseline 分支显式应用 updates（dry-run 仍只读）。
- **验收证据**：新增 `test_main_baseline_flag_writes_missing_baseline`（缺 baseline → 真实写入 `rating.last_status`）+ `test_main_baseline_flag_dry_run_writes_nothing`（dry-run 零写入）。

### 修复 2 · 写失败退出码不反映（中）
- **缺陷**：`main()` 循环内 write-error/read-error 仅计入 stats，脚本恒 exit 0；cron/包装脚本按「退出码非 0」告警（`run-state-change-hook.sh`），写失败会静默通过。
- **修复**：新增 `_exit_on_error(stats)`，stats 含 write-error/read-error 时 `sys.exit(1)`；JSON 与人类输出两条路径均生效；无错误不调用 exit（契约 exit 0）。
- **验收证据**：新增 `test_main_exits_1_on_write_error` / `test_main_json_exits_1_on_write_error`（写失败 exit=1）、`test_main_exits_1_on_read_error`（读失败 exit=1）、`test_main_no_error_exits_zero`（无错误不抛 SystemExit）。

### 退出码契约（写入模块 docstring）
| 场景 | 退出码 |
|------|:---:|
| 全部处理成功（含无事件、dry-run） | 0 |
| 汇总含 write-error / read-error | 1 |
