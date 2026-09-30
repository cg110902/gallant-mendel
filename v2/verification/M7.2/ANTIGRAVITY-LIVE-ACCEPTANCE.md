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
python studio.py branch create --book BOOK_ID --branch antigravity-check --json
python studio.py branch rollback --book BOOK_ID --branch antigravity-rollback-check --from-event EVENT_ID --json
python studio.py export --book BOOK_ID --format markdown,json,epub --json
```

对 M7.3 额外确认：两个 branch 操作前后 main head 不变；rollback 没有删除 EventLog 字节；重复 export 返回相同 `export_id`、`manifest_hash` 和文件 hashes。请在临时/测试书目执行 branch 命令。

## 回填真实 attestation

先运行：

```bash
python studio.py ide template --output /tmp/antigravity-live/input.json --json
```

将 transcript/截图/日志放在同一 bundle，按实际结果填写模板中的 IDE 版本、OS、带时区时间、operator、11 项 PASS/FAIL 与 evidence SHA-256，然后运行：

```bash
python studio.py ide attest --input /tmp/antigravity-live/input.json --output /tmp/antigravity-live/accepted.json --json
```

只有该命令成功生成 accepted bundle 后才算真实 live PASS；详见 `verification/M7.4/README.md`。不得修改 surrogate 报告中的 `vendor_runtime_executed=false`。
