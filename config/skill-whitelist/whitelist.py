#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skill-whitelist/whitelist.py — 岗位 × 技能 白名单与禁配规则引擎

版本: 1.0.0
制定: 资深战略领导者 · 2026-08-17
用途: 定义岗位类别与技能类型的匹配规则（白名单允许 + 禁配禁止），
      供技能分配、新增智能体/技能时的合规校验与周期性核查复用。

维护入口:
  - 主文件: config/skill-whitelist/whitelist.py
  - 规则文档: config/skill-whitelist/skill-whitelist-rule.md
  - 校验运行: python3 config/skill-whitelist/whitelist.py --verify  [可加 --agents-file <json>]

版本历史:
  - 1.0.0 (2026-08-17): 初始版本。7 岗位类别 × 12 技能类型，白名单矩阵 + 禁配规则。
      · 已应用到工作区全部 69 个智能体（1420 绑定，0 违规）。
      · 分类要点: 并行派发子代理归 PLAN；图像/安全放宽到数据/文档/培训/售前岗。

用法:
  1. 作为模块引用:
       import sys; sys.path.insert(0, 'config/skill-whitelist')
       from whitelist import ROLE_MAP, SKILL2TYPE, ALLOWED, FORBIDDEN, verify_agent_skills
  2. 命令行校验:
       python3 config/skill-whitelist/whitelist.py --verify --agents-file /path/to/agents-skills.json
  3. 新增智能体: 按岗位类别套用 ALLOWED[role] 分配技能，禁配类型不绑定。
  4. 新增技能: 先归入 SKILL_TYPE 某个类型，再据此决定可绑定的岗位类别。
"""

import argparse
import json
import os
import sys

__version__ = "1.0.0"

# ============ 岗位类别 → agent 名单 ============
MGMT = ['资深战略领导者', '项目负责人', '工作室运营', '高级项目经理', '会议记录专家', 'Jira 工作流管理员',
        'IT服务经理']
FIN = ['财务主管', '财务规划与分析分析师', '财务跟踪与规划专员']
SVC = ['客户服务与问题解决专员', '零售退货与客户恢复专家', '销售工程师', '销售教练',
       '语言翻译专家', '个人成长教练', '企业培训课程设计师']
CONTENT = ['内容创作者', '多平台出版商', '社交媒体师', '增长黑客', '抖音策略师', '小红书专家',
           '微信公众号经理', '知乎策略师', '百度SEO专家', 'B站内容战略师', '快手策略师', 'SEO优化专家',
           '播客策略师', '短视频剪辑教练专家', '微博策略师', '中国市场本地化策略师', '视频优化专家',
           '品牌战略家', '品牌守护者', '产品经理']
DESIGN = ['UI设计师', 'UI 设计师', '视觉设计专家', 'UI 完稿审核者', '包容性视觉专家',
          '轮播图自动生成专家', '趣味创意师']
DATA = ['实验追踪专家', '数据分析与洞察报告员', '趋势研究员', '数据工程师', '数据可视化工程师', '用户体验研究员',
        '数据可视化专家']
ENG = ['DevOps自动化工程师', '后端架构师', '软件架构师', '开发者工具工程师', '最小变更工程师',
       'SRE稳定性工程师', '前端工程师', '用户体验架构师', '多智能体系统架构师', '工作流程架构师',
       '代码审查员', '提示工程专家', '技术文档撰写者', 'AI 身份与信任架构师', '自动化治理架构师',
       'GitHub 仓库管理员', '事故响应指挥官', '专职QA测试工程师', '需求分析师 BA', '文档生成专家',
       '系统架构师', '站点可靠性工程师', '最小变更专家', 'OrgScript工程师', 'Drupal性能工程师',
       'WordPress性能工程师', '实时协作工程师', 'FinOps工程师', '数据库可靠性工程师']

ROLE_MAP = {}
for _n in MGMT: ROLE_MAP[_n] = 'MGMT'
for _n in FIN: ROLE_MAP[_n] = 'FIN'
for _n in SVC: ROLE_MAP[_n] = 'SVC'
for _n in CONTENT: ROLE_MAP[_n] = 'CONTENT'
for _n in DESIGN: ROLE_MAP[_n] = 'DESIGN'
for _n in DATA: ROLE_MAP[_n] = 'DATA'
for _n in ENG: ROLE_MAP[_n] = 'ENG'

ROLE_DESC = {
    'MGMT': '管理/流程', 'FIN': '财务', 'SVC': '客服/销售/培训',
    'CONTENT': '内容/营销/增长', 'DESIGN': '设计/创意', 'DATA': '数据/研究', 'ENG': '工程/技术',
}

# ============ 技能类型 → 技能 清单 ============
SKILL_TYPE = {
    'BASE': ['agent-skill-creator', '超级技能引导', '头脑风暴', '学习记录', '完成前验证',
             '沟通复述确认', '编写实现计划', '技能路由', '交接文档', '保存上下文', '恢复上下文'],
    'DEV_CORE': ['系统性调试', '测试驱动开发', '子代理驱动开发', '执行实现计划', 'Git工作区隔离',
                 '开发分支收尾', '解决合并冲突', '预提交钩子配置', '编写技能'],
    'DEV_REV': ['PR审查', '双轴代码审查', '请求代码审查', '接收代码审查', '代码质量仪表盘', '架构深化扫描'],
    'DEV_DEPLOY': ['落地部署', '金丝雀监控', '系统化QA', 'QA只报不修', '无头浏览', '发布工作流'],
    'DEV_DESIGN': ['快速原型', '深模块设计', '领域建模', '人工向导生成', '设计落地HTML', '设计质检',
                   '图表生成', '图表绘制'],
    'SEC': ['首席安全官', '命令安全护栏', '全量安全模式', '编辑冻结', '解除冻结'],
    'PLAN': ['规格落盘', '拆分工单', '工单分诊', '决策路径规划', '转化为问卷', '工程计划评审',
             'CEO计划评审', 'DX计划评审', '工程回顾', '自动评审流水线', '设计计划评审', '并行派发子代理'],
    'DESIGN_CR': ['多方案设计', '设计咨询', '设计落地HTML', '设计质检', '图表生成', '图表绘制'],
    'WRITE': ['素材挖掘', '写作成稿', '写作塑形', '面向智能体写作', '生成文档', '生成PDF', '发布文档更新',
              'officecli', 'anydoc'],
    'IMAGE': ['图像生成底座', '信息图生成', '文章封面图', '文章插图', '小红书图文卡', '幻灯片配图', '知识漫画'],
    'RESEARCH': ['一手来源调研', '网页抓取', '无头浏览'],
    'COACH': ['教学辅导', '方案压力测试', '追问打磨入口', '访谈产出文档'],
}

TYPE_DESC = {
    'BASE': '全员底座（纪律/引导/通用）', 'DEV_CORE': '核心开发（调试/测试/实现）',
    'DEV_REV': '代码审查与质量', 'DEV_DEPLOY': '部署与运维', 'DEV_DESIGN': '设计工程（原型/建模/图表）',
    'SEC': '安全治理', 'PLAN': '规划与管理（规格/工单/评审）', 'DESIGN_CR': '创意设计（方案/咨询/质检）',
    'WRITE': '内容写作与文档', 'IMAGE': '图像生成（配图/信息图/漫画）',
    'RESEARCH': '调研与采集', 'COACH': '教学与沟通',
}

# 技能 → 所属类型（反查，一个技能可属多类型）
SKILL2TYPE = {}
for _t, _s in SKILL_TYPE.items():
    for _s2 in _s:
        SKILL2TYPE.setdefault(_s2, set()).add(_t)

# ============ 白名单：岗位类别 → 允许技能类型 ============
ALLOWED = {
    'ENG': set(SKILL_TYPE.keys()),
    'DATA': {'BASE', 'DEV_CORE', 'DEV_REV', 'DEV_DEPLOY', 'DEV_DESIGN', 'SEC', 'PLAN', 'RESEARCH', 'WRITE', 'IMAGE', 'COACH'},
    'DESIGN': {'BASE', 'DEV_DESIGN', 'DESIGN_CR', 'IMAGE', 'PLAN', 'RESEARCH', 'COACH', 'WRITE'},
    'CONTENT': {'BASE', 'WRITE', 'IMAGE', 'RESEARCH', 'PLAN', 'COACH', 'DEV_DESIGN', 'DESIGN_CR'},
    'MGMT': {'BASE', 'PLAN', 'RESEARCH', 'COACH', 'WRITE', 'DESIGN_CR', 'DEV_DESIGN', 'DEV_REV'},
    'FIN': {'BASE', 'RESEARCH', 'COACH', 'WRITE', 'PLAN'},
    'SVC': {'BASE', 'RESEARCH', 'COACH', 'WRITE', 'PLAN', 'IMAGE', 'DESIGN_CR', 'DEV_DESIGN'},
}

# ============ 禁配规则：岗位类别 → 禁止技能类型 ============
FORBIDDEN = {
    'FIN': {'DEV_CORE', 'DEV_REV', 'DEV_DEPLOY', 'DEV_DESIGN', 'SEC', 'IMAGE', 'DESIGN_CR'},
    'SVC': {'DEV_CORE', 'DEV_REV', 'DEV_DEPLOY', 'SEC'},
    'CONTENT': {'DEV_CORE', 'DEV_DEPLOY', 'SEC'},
    'MGMT': {'DEV_CORE', 'DEV_DEPLOY', 'SEC'},
    'DESIGN': {'DEV_CORE', 'DEV_REV', 'DEV_DEPLOY', 'SEC'},
    'DATA': set(),
    'ENG': set(),
}


def role_of(agent_name):
    """返回 agent 所属岗位类别，未知返回 None。"""
    return ROLE_MAP.get(agent_name)


def skill_types(skill_name):
    """返回技能所属类型集合（未知返回 {'IDENTITY'} 视为身份技能）。"""
    return SKILL2TYPE.get(skill_name, {'IDENTITY'})


def is_allowed(role, skill_name, agent_names=None):
    """判断某岗位绑定某技能是否合规（白名单允许且非禁配）。

    身份技能（技能名 == agent 名 或属于 agent 名单）始终允许。
    """
    if agent_names and skill_name in agent_names:
        return True
    types = skill_types(skill_name)
    if 'IDENTITY' in types:
        return True
    allowed = ALLOWED.get(role, set())
    forbidden = FORBIDDEN.get(role, set())
    return any(t in allowed and t not in forbidden for t in types)


def verify_agent_skills(agent_skills, agent_names=None):
    """校验 agent→技能 映射，返回违规列表 [(agent, skill), ...]。"""
    violations = []
    for agent, skills in agent_skills.items():
        role = role_of(agent)
        if not role:
            continue
        for s in skills:
            if not is_allowed(role, s, agent_names):
                violations.append((agent, s))
    return violations


def main():
    parser = argparse.ArgumentParser(description='岗位×技能白名单/禁配规则引擎')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument('--verify', action='store_true', help='校验 agent→技能 映射是否合规')
    parser.add_argument('--agents-file', help='agent→技能 映射 JSON 文件（{agent: [skills]}）')
    args = parser.parse_args()

    print(f'岗位×技能白名单规则引擎 v{__version__}')
    if args.verify:
        if not args.agents_file or not os.path.exists(args.agents_file):
            print('❌ 需要 --agents-file 指向 agent→技能 映射 JSON')
            sys.exit(1)
        data = json.load(open(args.agents_file, encoding='utf-8'))
        viol = verify_agent_skills(data)
        if viol:
            print(f'⚠️ 发现 {len(viol)} 条违规：')
            for a, s in viol:
                print(f'   {a}: {s}')
            sys.exit(1)
        else:
            print(f'✅ 全部 {len(data)} 个 agent 技能绑定合规')
            sys.exit(0)


if __name__ == '__main__':
    main()
