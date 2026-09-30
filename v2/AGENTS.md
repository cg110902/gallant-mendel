# Novel Production OS · v2 实施规则

`v2/` 是唯一的实际工程根目录。架构说明位于 `../施工文档/`，仓库级入口位于 `../AGENTS.md`。

## 当前阶段

**M0–M5** 已完成；**M6.1–M6.7 Calibration、Warning Advisory、Challenge Transfer、三章恢复 Smoke 与三十章 Soak** 已通过。证据位于 `verification/M6.7/`。
下一步只能先评估 **M6.8 并发冲突与资源保护**；M6.7 仅证明受控顺序三十章可恢复，不得扩大为并发安全或生产可靠性结论。Challenge transfer 为 TP=9/FP=0/TN=18/FN=9；不得把 template holdout 满分扩大为自然语言可靠，也不得升级 hard gate。

先读：

1. `../施工文档/README.md`
2. `../施工文档/08-新会话实施交接与启动规范.md`
3. `../施工文档/09-M0精确施工与验收附录.md`
4. `../施工文档/10-跨文档勘误与补充冻结决策.md`
5. `../施工文档/11-ADR-0013-Python最低版本调整.md`
6. `../施工文档/12-M1.3对象协议补充冻结决策.md`
7. `../施工文档/13-M1.4投影与事件载荷补充冻结决策.md`
8. `../施工文档/14-M1.5快照与恢复补充冻结决策.md`
9. `../施工文档/15-M2.1大纲包布局与载入补充冻结决策.md`
10. `../施工文档/16-M2.2大纲语义索引与引用补充冻结决策.md`
11. `../施工文档/17-M2.3大纲领域完整性补充冻结决策.md`
12. `../施工文档/18-M2.4确定性编译产物与原子发布补充冻结决策.md`
13. `../施工文档/19-M2.5初始权威事件Bootstrap补充冻结决策.md`
14. `../施工文档/20-M2.6总验收与ContextPack前置就绪补充冻结决策.md`
15. `../施工文档/21-M3.1双时态与章节AsOf查询补充冻结决策.md`
16. `../施工文档/22-M3.2角色与读者知识边界补充冻结决策.md`
17. `../施工文档/23-M3.3FutureObligation生命周期补充冻结决策.md`
18. `../施工文档/24-M3.4IntentReality差异分类补充冻结决策.md`
19. `../施工文档/01-技术选型与冻结决策.md`
19. `../施工文档/02-核心协议与数据模型规范.md`
20. `../施工文档/07-大纲规格与编译规范.md`

## M0 规则

- 不接 API，不启动 Web 服务，不添加生产 Agent。
- 基础路径不依赖第三方包。
- 所有源代码、测试、fixture、验证产物都留在 `v2/`。
- 不把 `state.db` 或 `events.jsonl` 放在仓库根目录。
- 不修改施工文档中的冻结协议，除非写出明确变更记录。
- 先写测试和确定性入口，再扩展模块。

目标命令：

```bash
python studio.py version
python studio.py help
python studio.py doctor --no-api-key
python -m unittest discover -s tests -v
python scripts/verify_m0.py
```

每完成一项，更新 `施工状态/当前状态.md`，并保存验证证据到 `verification/M0/`。
