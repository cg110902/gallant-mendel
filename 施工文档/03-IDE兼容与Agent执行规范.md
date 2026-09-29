# IDE 兼容与 Agent 执行规范
## Antigravity 主目标，Claude Code / Cursor / Codex 兼容

---

## 1. 设计目标

本项目不是给每个 IDE 写一套业务逻辑，而是：

```text
Portable Core
  ├── studio.py
  ├── novel_kernel/
  ├── schemas/
  ├── scripts/
  └── .agents/skills/

Thin Adapters
  ├── Antigravity
  ├── Claude Code
  ├── Cursor
  └── Codex
```

所有 IDE 适配都只能改变：

- 技能发现位置
- 命令触发方式
- 权限和沙箱配置
- 子 Agent 启动方式
- Hook 生命周期映射

不能改变：

- 状态字段
- 事件格式
- 退出码
- ArtifactBundle
- 提交规则
- 验收规则

---

## 2. 目录规范

```text
AGENTS.md                         跨工具短规则
.agents/skills/<name>/SKILL.md    canonical 技能包
.agents/skills/<name>/scripts/    确定性辅助脚本
.agents/skills/<name>/references/ 仅按需读取的资料
.agents/rules/                    Antigravity 常驻规则
.agents/workflows/                Antigravity 兼容入口
.claude/                          Claude Code 薄适配
.cursor/                          Cursor 薄适配
.codex/                           Codex 薄适配
```

### 2.1 AGENTS.md 内容上限

`AGENTS.md` 只放：

- 项目是什么
- 入口命令
- 权威状态在哪里
- 绝对禁止事项
- 施工顺序
- 失败时看哪里

详细知识全部进入 Skill 或 references。推荐不超过 200 行；超过必须拆分。

### 2.2 Skill 格式

```markdown
---
name: draft-chapter
description: Generate a chapter beat from a validated ContextPack without modifying authoritative state.
---

# Skill: draft-chapter

## Use when
...

## Must read
...

## Allowed actions
...

## Forbidden actions
...

## Procedure
1. ...

## Exit evidence
...
```

Skill 只允许描述流程和调用脚本；硬规则应在脚本和内核中再次执行。

---

## 3. Canonical Skills

首批技能：

```text
novel-doctor          检查 Agent 布局、Python、权限、目录
novel-init            初始化书籍和 Outline Package
outline-validate      校验输入规格
outline-compile       把大纲编译成状态和生产任务
state-query           查询当前权威状态
build-context         生成 ContextPack
plan-chapter          生成章/beat 计划
write-beat            生成候选正文，不写权威状态
extract-artifact      从正文抽取候选事实和状态变化
reconcile-state       意图/实况平账
safety-audit          硬一致性与权限审计
style-audit           文风、重复、节奏审计
reader-audit          读者知识和悬念审计
commit-chapter        通过所有门禁后提交章节
resume-production     从快照和生产清单恢复
snapshot-book         创建可恢复快照
rollback-book         分支/回滚/重产
calibrate-gates       运行离线写手、变异测试和阈值标定
```

---

## 4. Agent 角色与权限

### 4.1 Architect

可读：大纲、配置、历史状态。

可写：候选规划产物、人工审批请求。

不可写：正文、事件日志、权威状态。

### 4.2 Planner

可读：当前卷、章、开放义务、角色和读者状态。

可写：`intent_contract`、beat DAG、风险清单。

不可写：已确认事实。

### 4.3 Writer

可读：ContextPack、当前任务、有限近期正文。

可写：`prose.md`、写作备注。

不可写：`state.db`、`events.jsonl`、权威对象定义。

### 4.4 Extractor

可读：候选正文与 ContextPack。

可写：候选 claims、candidate delta、证据区间。

不可写：直接提交权威状态。

### 4.5 Auditor

可读：原始契约、权威状态、候选正文、候选抽取结果。

可写：报告、违规项、证据。

不可写：正文和状态。

### 4.6 Reconciler

首期是确定性 Python 模块，不是 Agent。

可写：经验证的事件和派生投影。

### 4.7 Librarian

可读：已提交内容和审计结果。

可写：摘要、索引、经验 delta 候选。

经验写入必须经过 Curator/合并器和回归检查。

---

## 5. Antigravity 执行面

### 5.1 主要使用方式

- Workspace：打开 `/home/user/novel-pipeline`
- Skills：`.agents/skills`
- Rules：`.agents/rules`
- Workflow：只作为 `/novel-*` 兼容入口
- Python：`python studio.py ...`

### 5.2 推荐入口

```text
/novel-init
/novel-validate
/novel-plan ch_001
/novel-write ch_001
/novel-audit ch_001
/novel-commit ch_001
/novel-resume
```

所有入口最终调用 `studio.py`，而不是把业务逻辑写在 Workflow 文本里。

### 5.3 Antigravity 特有规则

可放在 `.agents/rules/` 的内容：

- 该项目是本地小说生产系统。
- 优先使用 `.agents/skills`。
- 任何正文提交必须执行 `studio.py check`。
- 任何权威状态写入必须经过 `studio.py reconcile/commit`。
- 无 API Key 模式必须保持可运行。

---

## 6. Claude Code 执行面

适配文件：

```text
.claude/CLAUDE.md
.claude/agents/*.md
.claude/settings.example.json
```

策略：

- `CLAUDE.md` 是 `AGENTS.md` 的薄适配，不复制详细规则。
- Subagent 用于审计、抽取和检索隔离。
- Hook 可调用 `studio.py check --incremental`。
- Hook 失败必须让当前任务失败或进入人工断点。
- 不把核心规则只写在 Claude Hook 中。

---

## 7. Cursor 执行面

适配文件：

```text
.cursor/rules/*.mdc
.cursor/agents/
.cursor/hooks.example.json
```

策略：

- `AGENTS.md` 是基础规则。
- `.cursor/rules` 只增加路径范围和 Cursor 特有触发信息。
- Explore/Bash/Browser 子 Agent 用于隔离噪声。
- 写手只获得 `build-context` 生成的 ContextPack，不自行扫描全库。
- 背景 Agent 的结果必须落盘到 `runs/<run_id>`，不能只存在对话中。

---

## 8. Codex 执行面

适配文件：

```text
.codex/config.example.toml
.agents/skills/
AGENTS.md
```

策略：

- 使用 `codex exec` 做批处理和 CI。
- 使用 sandbox 和 approval policy 限制写入。
- 用 `codex resume/fork` 对应系统的 Run/Branch。
- 模型配置不是业务协议的一部分。
- `AGENTS.md` 保持足够短，技能按需加载。

---

## 9. MCP 使用边界

MCP 只能提供可选工具：

```text
MCP 可以提供：
- 资料检索
- 浏览器/网页
- 外部文档
- 本地数据库工具
- 图像/音频辅助

MCP 不能成为：
- 权威事件日志
- 唯一状态数据库
- 必需的模型服务
- 提交闸门
```

没有 MCP 时，核心路径仍然必须运行。

---

## 10. Agent 执行安全规则

### 写入权限

```text
Writer             仅 runs/<run_id>/
Extractor          仅 runs/<run_id>/
Auditor            仅 runs/<run_id>/audits/
Reconciler         由 studio.py 执行
Commit             仅 studio.py
```

### 状态写入防护

任何 Agent 直接修改以下文件都视为违规：

```text
ledger/events.jsonl
state/state.db
production/manifest.yaml
snapshots/*/manifest.json
```

### 会话恢复

新会话必须先读：

1. `production/manifest.yaml`
2. 最近 snapshot
3. 最近 3 个 run 的 `final-status.json`
4. 未决人工断点
5. 当前分支头事件

不能从聊天记录猜测状态。

---

## 11. 兼容性自检命令

施工后提供：

```bash
python studio.py doctor --agent-layout
python studio.py doctor --skills
python studio.py doctor --permissions
python studio.py doctor --no-api-key
```

检查：

- Python 版本
- 技能发现路径
- 必要脚本可执行
- 输出目录可写
- 权威文件没有被 Agent 规则授予直接写权限
- 无 API Key 时核心命令仍可运行
- IDE 适配文件是否过期

---

## 12. 兼容性验收

每个目标 IDE 至少完成：

1. 发现 `novel-doctor` Skill。
2. 运行初始化命令。
3. 生成一个 ContextPack。
4. 执行 Writer 并产出 `prose.md`。
5. Writer 不能直接改 `state.db`。
6. Auditor 发现一个故意注入的硬错误。
7. Commit 被硬错误拦截。
8. 删除派生数据库后可重建。
9. 中断后可以 resume。
10. 不配置 API Key 时 `doctor/check/snapshot/export` 成功。
