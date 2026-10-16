# 南枫转写 Windows 当前状态

## Verified
- Last verified: 2026-10-16 +08:00
- Branch: main
- Status: VERIFIED — v1.0.9 Windows formal release.
- Scope: 本地转写历史、画面内播放器与本轮界面整理。

## Current
- 新增 SQLite 历史快照、全文搜索/时间筛选、编辑/复制/再次导出、批量删除；升级不会补造旧版未保存历史，删除不影响源媒体和外部导出。
- 视频画面内统一播放、进度、音量、倍速、字幕、全屏与续播；字幕单击跳转，按时间范围显示；当前字幕浅橙选中。
- 历史卡片单行摘要、彩色属性、圆圈复用批量选择；列表与外层灰底统一。文稿直接编辑，单行精简标题、图标返回、格式居中。
- 文稿 15px 字体、轻微字距、1.7 倍行距、自适应阅读栏与内部留白；Windows 原生行尾回归检查已通过，不改变保存内容。
- 队列表头共享轮廓；打开输出目录移至操作栏，设置移除功能审阅，总进度蓝色。
- 保持精简安装包、按需模型环境和已有模型缓存；安装向导简体中文，Windows 安装包 NotSigned。
- 产品版本唯一来源 `app/assets/product.json`；当前合同见 [CONTRACTS.md](CONTRACTS.md)，发布收据见 [release-v1.0.9.json](release-v1.0.9.json)。

## Tests
- 最终 92 项完整测试、23 项发布合同门禁通过；测试、构建及隔离验收日志在 `.runtime/qa/release-v109/`。
- 固定目录冻结程序构建通过。专用 QA AppId 隔离安装/启动/卸载通过，844 个安装文件与构建文件逐一哈希一致。
- 安装版受控视频帧有效、播放进度推进、字幕同步，无解码错误；README 四张独立截图来自本次安装负载。
- 安装脚本 Windows PowerShell 5 复用既有运行环境校验通过（CUDA True）；离线受控语音转写生成 45 字符及 TXT/SRT，无新增模型下载。

## Gaps
- 正式 AppId 覆盖用户真实安装未执行；隔离 QA 使用相同应用负载与独立安装身份。
- 真实用户媒体准确率、外部文本 API、全编码/多物理 DPI 未验收。既有运行生命周期及进度聚合债务仍见 [contract-audit.md](contract-audit.md)。

## Sync & Safety
- 基线 `835512ddb6cd1412b0fb6271af4a514c6362d5e4`；旧发布包不改写。固定复用 `build` / `dist_release_current`。
- 用户设置、媒体、外部导出、模型和凭据未提交；`docs/ui-design-baseline.md` 为既有其他任务文件，保留不纳入本次发布。

## Release
- [v1.0.9 下载与版本说明](https://github.com/nanzhufeng/NanfengTranscriber-Windows/releases/tag/v1.0.9)，正式发布已核对（draft=false、prerelease=false）；仅一个 EXE，167087862 字节及 SHA-256 与本地一致，标签指向应用源码 `d18b100b4598e5a79e6952509f0ad362a23366db`。

## Next
- 保留本次收据与轻量证据；下一功能改动重新核对合同与状态，不扩大已有验收结论。
