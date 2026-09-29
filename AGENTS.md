# Novel Production OS · 实施入口

本文件是任何新会话、新 Agent、新 IDE 打开本仓库时的第一入口。

## 1. 当前状态

- 项目：Novel Production OS
- 当前阶段：**M0–M5 已完成；M6.1 Offline Oracle 与 Mutation/Calibration Foundation 已通过验收**
- 架构施工文档：`施工文档/`
- 实际工程根目录：`v2/`
- 代码状态：确定性内核已包含原子存储、事件日志、对象模型、SQLite 投影、Snapshot/restore、双时态查询、知识边界和 Future Obligation 生命周期
- 当前目标：先评估并冻结 M6.2 executable mutation harness，让 gold corpus 经过真实 M5 gates 并产生 baseline confusion report
- 验收证据：`v2/verification/M0/` 至 `v2/verification/M6.1/` 的全部已完成阶段目录

不要把“M0 已完成”误解为小说生产能力已经实现。

## 2. 必须先读的文件

按以下顺序读取：

1. `施工文档/README.md`
2. `施工文档/08-新会话实施交接与启动规范.md`
3. `施工文档/09-M0精确施工与验收附录.md`
4. `施工文档/10-跨文档勘误与补充冻结决策.md`
5. `施工文档/11-ADR-0013-Python最低版本调整.md`
6. `施工文档/12-M1.3对象协议补充冻结决策.md`
7. `施工文档/13-M1.4投影与事件载荷补充冻结决策.md`
8. `施工文档/14-M1.5快照与恢复补充冻结决策.md`
9. `施工文档/15-M2.1大纲包布局与载入补充冻结决策.md`
10. `施工文档/16-M2.2大纲语义索引与引用补充冻结决策.md`
11. `施工文档/17-M2.3大纲领域完整性补充冻结决策.md`
12. `施工文档/18-M2.4确定性编译产物与原子发布补充冻结决策.md`
13. `施工文档/19-M2.5初始权威事件Bootstrap补充冻结决策.md`
14. `施工文档/20-M2.6总验收与ContextPack前置就绪补充冻结决策.md`
15. `施工文档/21-M3.1双时态与章节AsOf查询补充冻结决策.md`
16. `施工文档/22-M3.2角色与读者知识边界补充冻结决策.md`
17. `施工文档/23-M3.3FutureObligation生命周期补充冻结决策.md`
18. `施工文档/24-M3.4IntentReality差异分类补充冻结决策.md`
19. `施工文档/00-项目施工总纲.md`
19. `施工文档/01-技术选型与冻结决策.md`
20. `施工文档/02-核心协议与数据模型规范.md`
21. `施工文档/04-分阶段施工计划与任务清单.md`

需要了解 IDE 适配时，再读 `03-IDE兼容与Agent执行规范.md`；需要了解运行和验证时，再读 `05-验证体系与验收标准.md`、`06-运行手册与故障恢复规范.md`、`07-大纲规格与编译规范.md`。

## 3. 不可违反的约束

- 代码只能施工在 `v2/`，不要把 `studio.py`、源代码或运行数据写到仓库根目录。
- 核心确定性路径不能依赖 API Key、云服务、常驻 Web 服务或向量/图数据库。
- 基础路径不能要求第三方 Python 包；可选依赖必须有明确降级路径。
- 事件日志是历史权威；SQLite 是可重建投影；Run 产物不是权威状态。
- Writer、Extractor、Auditor 不得直接修改权威状态。
- 只有 Reconciler/Commit 代码可以追加权威事件。
- 不要用 IDE 对话历史替代文件、事件、快照或进度记录。
- 不得跳过 M0，直接实现正文生产 Agent。
- 不得静默改变 ADR、协议字段、退出码或目录契约；发现冲突时先记录补充决策。

## 4. 新会话的第一动作

在仓库根目录执行：

```bash
cd v2
python --version
python -m unittest discover -s tests -v
```

`tests/` 与 `studio.py` 现已存在；如果缺失，应视为仓库损坏并先对照证据恢复，不能静默创建另一套入口。开始任何新子任务前先更新 `v2/施工状态/当前状态.md`，说明范围与排除项。

M0 的回归命令为：

```bash
python studio.py version
python studio.py help
python studio.py doctor
python studio.py doctor --no-api-key
python -m unittest discover -s tests -v
python scripts/verify_m0.py
```

## 5. 施工纪律

每完成一个小任务：

1. 运行对应测试。
2. 记录命令和结果。
3. 更新 `v2/施工状态/当前状态.md`。
4. 不顺手实现下一阶段功能。

每个里程碑完成时，必须在 `v2/verification/<milestone>/` 保存命令日志、测试结果、失败样本和已知限制。

## 6. 发生冲突时

优先级从高到低：

1. `施工文档/10-跨文档勘误与补充冻结决策.md`
2. `施工文档/09-M0精确施工与验收附录.md`
3. 已冻结 ADR
4. 核心协议
5. 阶段任务清单
6. 运行手册和 IDE 示例

如果无法按优先级解决，停止扩展实现，写一份 ADR 或变更记录，不要凭感觉选一个。

## 7. 完成回复必须包含

- 改动了哪些文件
- 运行了哪些命令
- 每条命令的结果和退出码
- 哪些验收条件已满足
- 哪些没有满足
- 下一步只能做什么
- 是否发生了架构或协议变更
