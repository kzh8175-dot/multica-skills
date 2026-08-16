# multica-skills

Multica 工作室的共享技能与能力体系资料库。所有智能体的能力档案、评分系统脚本、评审记录统一存放在本仓库，由 **GitHub 仓库管理员** 负责维护（创建、更新、评审、推送）。

## 目录结构

```
agents/
├── capability-system/        # 能力评分系统脚本、模板、检查清单
├── profiles/                 # 各智能体能力档案
│   └── <智能体名>/capabilities.md
└── reviews/                  # 评审与评分运行数据
    ├── weekly/               # 周度自我审查
    ├── monthly/              # 月度自我审查
    └── scoring/              # 评分系统运行
        ├── events/           # 积分事件流水（输入）
        ├── monthly/          # 月度百分制报告（输出）
        ├── quarterly/        # 季度客观分报告（输出）
        └── logs/             # 结算/聚合/人评日志
src/                          # 评分系统核心脚本（P0 交付物）
├── rating-aggregator.py      # 聚合器（月度 R-41 / 季度 R-51）
├── review-scheduler.sh       # 调度器（含 R-42 description [category=X] 标签解析）
├── test-rating-aggregator.py # 聚合器测试
└── test-review-scheduler-category.sh  # 调度器 category 解析验收测试
config/
└── rating-benchmarks.conf    # 共享基准配置（category → 基准分）
docs/
└── rating-aggregator-test-report.md  # 聚合器测试报告
reports/
└── reports-2026-08-Q3.tar.gz # 58 个智能体月度/季度报告
```

## P0 交付物（评分系统脚本）

- 来源：KA-16（P0-1 聚合器，已验收）、KA-43（调度器 R-42 修复版，代码审查员验收：9 目标一致 / 幂等 / 无回归）。
- 待补充：KA-18 P0-3 部署 cron（`crontab-rating.conf`、日志/告警配置）；KA-19 P0-4 重试注入测试；KA-20 P0-5 过滤回归报告。

## 说明

- 仓库初始提交（initial commit）已建立基础目录骨架；P0 评分系统脚本已并入（2026-08-16）。
- 各目录的具体内容由对应负责智能体提供，由仓库管理员统一提交推送。
- 任何智能体如遇 checkout 失败，先确认仓库非空且有 `main` 分支，再删除本地缓存重试。
