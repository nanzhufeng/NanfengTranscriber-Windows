# 历史证据索引

这些资料只说明当时的实现和验证，不是当前合同。当前规则见 [CONTRACTS.md](CONTRACTS.md)。旧型号、版本、截图、ZIP 和旧签名策略不能恢复为默认规则。

完整旧文档固定保存在审计前提交 1b903867027627b17a5fee2ce82ad4d4cf52074c：

- [旧架构 Context](https://github.com/nanzhufeng/NanfengTranscriber-Windows/blob/1b903867027627b17a5fee2ce82ad4d4cf52074c/docs/context.md)
- [旧产品上下文](https://github.com/nanzhufeng/NanfengTranscriber-Windows/blob/1b903867027627b17a5fee2ce82ad4d4cf52074c/docs/chatgpt-project-context.md)
- [旧完整交接](https://github.com/nanzhufeng/NanfengTranscriber-Windows/blob/1b903867027627b17a5fee2ce82ad4d4cf52074c/docs/CURRENT_HANDOFF.md)

本仓库保留的历史证据：

- [早期经验矩阵](development-experience-audit.md)
- [2026-07 性能方案](superpowers/specs/2026-07-15-transcription-performance-optimization-design.md) 与 [执行记录](superpowers/plans/2026-07-15-transcription-performance-optimization.md)
- `docs/superpowers/benchmarks/` 原始基准 JSON：当时 medium 与 RTX 4090 的数据，不能当作当前 Qwen/Turbo 对比结果；含当时样本路径，勿作为公开展示素材。
- `docs/RELEASE_NOTES_v1.0.0.md` 至 `v1.0.4.md` 是旧版本说明。
- [v1.0.5 发布收据](release-v1.0.5.json)、[v1.0.6 发布收据](release-v1.0.6.json) 是已发布文件的不可改写证据。
- `tests/ui_baselines/windows/` 是旧四档离屏布局资产，完整性检查不等于当前多 DPI 验收。

`build_windows_installer.ps1` 和 `installer/install.*` 保留历史 IExpress 兼容能力，不执行、不推荐为正式构建；其旧 ZIP 文案不定义当前产品。当前入口是 Inno，其他平台正式签名要求独立执行。
