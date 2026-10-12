# 南枫转写 Windows 当前状态

## Verified
- Last verified: 2026-10-12 +08:00
- Branch: main
- Status: VERIFIED — v1.0.7 release artifact
- Scope: 合同统一与列表选中、表头边缘的界面修正，保持现有转写和导出功能。

## Current
- 当前合同唯一正文 [CONTRACTS.md](CONTRACTS.md)，架构所有者见 [context.md](context.md)，审计与保留债务见 [contract-audit.md](contract-audit.md)。
- 产品版本由 `app/assets/product.json` 拥有；模型显示来自目录，UI 资产归本项目，GPU 预检查复用推理端探测。
- 模式选中行浅灰底与左侧细红条，无整圈描边。队列表头灰底贴齐顶部和左右；语言、模式、定位控件透明，选中仅使用表格自身底色。
- [v1.0.7 发布入口](https://github.com/nanzhufeng/NanfengTranscriber-Windows/releases/tag/v1.0.7)，产物与校验见 [发布收据](release-v1.0.7.json)。远端发布状态须独立读取 GitHub 元数据确认。
- 安装器 159,822,661 字节（约 152.4 MiB），NotSigned；精简安装与按需本地运行环境继续保留。

## Tests
- 完整 57 项测试、23 项合同门禁与 Python 编译检查通过。
- 冻结构建及实际界面截图通过；独立 QA AppId 安装/启动/卸载通过，784 个安装文件与构建目录逐文件哈希一致。
- 冻结程序禁用网络的受控中文语音转写通过：45 字符、TXT/SRT，4 条有效且不重叠的时间段。
- README 主窗口与设置图来自本次安装版；历史审计证据保持原有验证范围。

## Gaps
- 真实用户媒体准确率、真实文本 API、多物理 DPI 和审计登记的运行行为债务仍未补验；详见审计，不借发布改变行为。
- 正式 AppId 的覆盖安装未在用户真实安装上运行；隔离安装使用独立 QA AppId 与相同程序负载。

## Sync & Safety
- 发布前基线 `1b903867027627b17a5fee2ce82ad4d4cf52074c`；既有 v1.0.6 包与收据不改写。
- 固定复用 `build` / `dist_release_current`；本次隔离证据在 `.runtime/qa/release-v107/`。用户设置、媒体、输出、模型缓存与凭据不提交或修改。

## Next
1. 优先专项验证任务运行时关闭窗口的生命周期收尾。
2. 在独立任务处理审计登记的行为债务。
