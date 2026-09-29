# Novel Production OS · v2 实施规则

`v2/` 是唯一的实际工程根目录。架构说明位于 `../施工文档/`，仓库级入口位于 `../AGENTS.md`。

## 当前阶段

当前处于 **M0：工程宪法与最小入口**，实际代码尚未开始。

先读：

1. `../施工文档/README.md`
2. `../施工文档/08-新会话实施交接与启动规范.md`
3. `../施工文档/09-M0精确施工与验收附录.md`
4. `../施工文档/10-跨文档勘误与补充冻结决策.md`
5. `../施工文档/01-技术选型与冻结决策.md`
6. `../施工文档/02-核心协议与数据模型规范.md`

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
