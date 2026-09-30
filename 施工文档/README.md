# Novel Production OS · 施工文档集

这是本项目的可执行施工文档，不是宣传材料。

## 推荐阅读顺序

### 新会话/开始施工时

1. 仓库根目录 `../AGENTS.md`
2. [08-新会话实施交接与启动规范](./08-新会话实施交接与启动规范.md)
3. [09-M0精确施工与验收附录](./09-M0精确施工与验收附录.md)
4. [10-跨文档勘误与补充冻结决策](./10-跨文档勘误与补充冻结决策.md)
5. [11-ADR-0013-Python最低版本调整](./11-ADR-0013-Python最低版本调整.md)
6. [12-M1.3对象协议补充冻结决策](./12-M1.3对象协议补充冻结决策.md)
7. [13-M1.4投影与事件载荷补充冻结决策](./13-M1.4投影与事件载荷补充冻结决策.md)
8. [14-M1.5快照与恢复补充冻结决策](./14-M1.5快照与恢复补充冻结决策.md)
9. [15-M2.1大纲包布局与载入补充冻结决策](./15-M2.1大纲包布局与载入补充冻结决策.md)
10. [16-M2.2大纲语义索引与引用补充冻结决策](./16-M2.2大纲语义索引与引用补充冻结决策.md)
11. [17-M2.3大纲领域完整性补充冻结决策](./17-M2.3大纲领域完整性补充冻结决策.md)
12. [18-M2.4确定性编译产物与原子发布补充冻结决策](./18-M2.4确定性编译产物与原子发布补充冻结决策.md)
13. [19-M2.5初始权威事件Bootstrap补充冻结决策](./19-M2.5初始权威事件Bootstrap补充冻结决策.md)
14. [20-M2.6总验收与ContextPack前置就绪补充冻结决策](./20-M2.6总验收与ContextPack前置就绪补充冻结决策.md)
15. [21-M3.1双时态与章节AsOf查询补充冻结决策](./21-M3.1双时态与章节AsOf查询补充冻结决策.md)
16. [22-M3.2角色与读者知识边界补充冻结决策](./22-M3.2角色与读者知识边界补充冻结决策.md)
17. [23-M3.3FutureObligation生命周期补充冻结决策](./23-M3.3FutureObligation生命周期补充冻结决策.md)
18. [24-M3.4IntentReality差异分类补充冻结决策](./24-M3.4IntentReality差异分类补充冻结决策.md)
19. [25-M3.5张力集合指标与Impact补充冻结决策](./25-M3.5张力集合指标与Impact补充冻结决策.md)
20. [26-M4.1ProductionTaskDAG与ContextPack补充冻结决策](./26-M4.1ProductionTaskDAG与ContextPack补充冻结决策.md)
21. [27-M4.2WriterRuntime与Run控制补充冻结决策](./27-M4.2WriterRuntime与Run控制补充冻结决策.md)
22. [28-M4.3Provider预算与HumanCheckpoint补充冻结决策](./28-M4.3Provider预算与HumanCheckpoint补充冻结决策.md)
23. [29-M5.1CandidateClaims与EvidenceBinding补充冻结决策](./29-M5.1CandidateClaims与EvidenceBinding补充冻结决策.md)
24. [30-M5.2CandidateReconcile与硬闸门前置分类补充冻结决策](./30-M5.2CandidateReconcile与硬闸门前置分类补充冻结决策.md)
25. [31-M5.3DeterministicHardAudit补充冻结决策](./31-M5.3DeterministicHardAudit补充冻结决策.md)
26. [32-M5.4SemanticStyleReport与ReworkGate补充冻结决策](./32-M5.4SemanticStyleReport与ReworkGate补充冻结决策.md)
27. [33-M5.5ChapterCommitTransaction补充冻结决策](./33-M5.5ChapterCommitTransaction补充冻结决策.md)
28. [34-M5总回归与单章端到端验收补充冻结决策](./34-M5总回归与单章端到端验收补充冻结决策.md)
29. [35-M6.1OfflineOracle与MutationCorpus补充冻结决策](./35-M6.1OfflineOracle与MutationCorpus补充冻结决策.md)
30. [36-M6.2ExecutableMutationHarness补充冻结决策](./36-M6.2ExecutableMutationHarness补充冻结决策.md)
31. [37-M6.3SoftFeature与DataSplit补充冻结决策](./37-M6.3SoftFeature与DataSplit补充冻结决策.md)
32. [38-M6.4Threshold冻结与OneShotHoldout补充冻结决策](./38-M6.4Threshold冻结与OneShotHoldout补充冻结决策.md)
33. [39-M6.5AdvisoryDetector与ChallengeTransfer补充冻结决策](./39-M6.5AdvisoryDetector与ChallengeTransfer补充冻结决策.md)
34. [40-M6.6三章连续提交与恢复Smoke补充冻结决策](./40-M6.6三章连续提交与恢复Smoke补充冻结决策.md)
34. [00-项目施工总纲](./00-项目施工总纲.md)
35. [01-技术选型与冻结决策](./01-技术选型与冻结决策.md)
36. [02-核心协议与数据模型规范](./02-核心协议与数据模型规范.md)
37. [04-分阶段施工计划与任务清单](./04-分阶段施工计划与任务清单.md)

### 按需阅读

22. [07-大纲规格与编译规范](./07-大纲规格与编译规范.md)
23. [03-IDE兼容与Agent执行规范](./03-IDE兼容与Agent执行规范.md)
24. [05-验证体系与验收标准](./05-验证体系与验收标准.md)
25. [06-运行手册与故障恢复规范](./06-运行手册与故障恢复规范.md)

## 当前冻结结论

- 项目名称：Novel Production OS
- 主要目标：Antigravity
- 兼容：Claude Code / Cursor / Codex
- 默认运行：IDE Agent，无 API Key 依赖
- 核心语言：Python 3.11+
- 核心存储：append-only 事件日志 + SQLite 派生投影 + Markdown/JSON 证据
- 核心模型：Object + Facet + Relation
- 核心时间：双时态 + 叙事序
- 核心状态：过去事实 + 未来义务 + 角色/读者知识
- 核心交换：ContextPack + ArtifactBundle
- 核心入口：`python studio.py ...`
- 核心原则：模型写文学，确定性内核管物理事实
- 首期不依赖：云 API、向量数据库、图数据库、常驻 Web 服务、多 Agent 群聊

## 当前施工状态

```text
调研                     ✅ 完成
技术选型                 ✅ 已形成 ADR 基线
核心协议                 ✅ 已形成 v3 协议草案
大纲规格                 ✅ 已形成 Outline Package v1
IDE 兼容                 ✅ 已形成跨工具规范
施工计划                 ✅ M0–M8 已拆分
验证与运维               ✅ 已形成验收和恢复规范
新会话交接               ✅ 已补充，含仓库级 AGENTS.md
M0 精确验收附录          ✅ 已补充
跨文档勘误与路径冻结     ✅ 已补充
M0 工程宪法与最小入口    ✅ 已完成并保存 verification/M0 证据
M1 确定性内核            ✅ 已完成，10,000 事件与 Snapshot restore 验收通过
M2 大纲编译              ✅ M2.1–M2.6 已完成，总验收与首章前置 readiness 通过
M3 叙事状态与知识层      ✅ M3.1–M3.5 已完成
M4 小说生产流水线        ✅ M4.1–M4.3 已完成
M5 抽取审计与提交        ✅ M5 总回归与单章端到端验收已通过
M6 标定、对抗与压测      🚧 M6.1–M6.6 已通过，三章恢复 smoke 无静默丢失
```

实际工程根目录已经冻结为：

```text
<repository-root>/v2/
```

## 当前下一步

M0–M5 与 M6.1–M6.6 已通过；三章恢复 smoke 证据位于 `v2/verification/M6.6/`。下一步只能先评估 M6.7：

1. 执行三章连续 plan/context/audit/advisory/commit 闭环。
2. 冻结三章 CED 与 state/event/chapter 数量守恒检查。
3. 注入中断并从 snapshot/transaction journal 恢复，验证无 silent data loss。
4. Challenge 的 9 个 FN 必须继续可见，不得用 smoke 通过替代 detector 迁移证据。

## 重要规则

- 不跳过协议直接写生产 Agent。
- 不把 IDE 对话历史当作项目数据库。
- 不让 Writer 直接修改权威状态。
- 不以“模型说完成”作为验收证据。
- 不在没有基准和回归集的情况下调宽阈值。
