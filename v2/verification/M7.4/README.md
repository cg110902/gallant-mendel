# M7.4 Antigravity Live Attestation Kit

工具链已通过；真实 Antigravity 运行仍为 **PENDING**。

在 Antigravity 中：

```bash
cp verification/M7.4/antigravity-live-input.template.json /tmp/antigravity-live/input.json
# 将 terminal transcript、截图或日志放在 /tmp/antigravity-live/ 内；
# 按实际结果填写 IDE version、OS、时间、operator、11 项 status 和 evidence SHA-256。
python studio.py ide attest \
  --input /tmp/antigravity-live/input.json \
  --output /tmp/antigravity-live/accepted.json \
  --json
```

每个 evidence hash 格式为 `sha256:<64 lowercase hex>`；路径相对 `input.json`，不可逃出 bundle。允许多项检查绑定同一份完整 transcript，但不得绑定不存在或事后被修改的文件。

只有命令成功生成 `accepted.json` 后，才可把 Antigravity live acceptance 记录为 PASS。请勿直接修改 `verification/M7.2/compatibility-matrix.json` 的 `vendor_runtime_executed=false`。
