# Antigravity Live Acceptance（待用户执行）

> 当前状态：**PENDING**。本文件不是厂商 runtime 已通过的证明。

在 Antigravity 直接打开 `v2/`，依次执行：

1. `/novel-status`：确认能发现 `.agents/skills/*/SKILL.md` 与项目状态。
2. `/novel-init`：在临时 workspace 初始化；不得覆盖已有权威文件。
3. `/novel-context`：生成可追踪 ContextPack。
4. `/novel-write`：仅生成 Writer candidate，确认未直接写 EventLog/state/snapshot manifest/compiled authority/committed chapters。
5. `/novel-review`：对 candidate 执行审查和 hard-error 检测。
6. `/novel-commit`：hard error 输入必须阻止提交；合格输入才可走正式提交路径。

随后在 Antigravity terminal（项目根为 `v2/`）运行：

```bash
python studio.py doctor --agent-layout --no-api-key --json
python -m novel_kernel.compatibility_matrix --output verification/M7.2/compatibility-matrix.json
```

## 回填真实 attestation

请保留：执行日期、Antigravity 版本、OS、六个 workflow 各自 PASS/FAIL、doctor JSON、失败日志/截图，以及操作者签名。全部通过后另建 `antigravity-live-attestation.json`，不得修改 surrogate 报告中的 `vendor_runtime_executed=false`。
