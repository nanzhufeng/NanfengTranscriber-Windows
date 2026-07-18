# 南枫转写 Windows v1.0.0

这是项目的首个 GitHub 版本，提供 Windows 可点击安装包和完整源码。

## 主要功能

- 批量导入视频、音频和文件夹，支持拖放。
- 本地 faster-whisper 转写，默认 `medium` 模型。
- GPU 优先、CPU 稳定模式和运行时自动降级。
- 队列级模型复用与 GPU 批量推理。
- 导出 TXT、Markdown、SRT、DOCX。
- 可选的转写后翻译/润色模块。
- 已有结果覆盖或跳过后继续处理。
- 每个 Whisper 模型首次成功下载后长期复用，升级或重装软件不重复下载。

## 本版修复

- 修复 PyInstaller 安装版点击“开始转写”后可能长时间无响应的问题。
- 冻结版不再在界面主线程扫描已打包的 Python 依赖和 NVIDIA Python 包。
- 保留 PATH 和系统 CUDA 运行库检测，并增加启动阶段日志。
- 增加文本 API 鉴权、超时、空响应和异常响应回归。
- Windows 安装器切换到 Inno Setup，安装说明优先使用中文。

## 安装说明

1. 下载 Windows 安装包 ZIP。
2. 完整解压 ZIP。
3. 双击 `NanfengTranscriber_Windows_v1.0.0_Setup_*.exe`。
4. 首次运行某个模型时保持网络连接，等待模型下载完成。

## 已知边界

- 安装包未进行商业代码签名，可能触发 Windows SmartScreen。
- GPU 加速依赖兼容的 NVIDIA 驱动、CUDA、cuBLAS 和 cuDNN；不可用时可使用 CPU。
- 翻译/润色需要单独配置文本 API 密钥，原始本地转写不需要该密钥。
- macOS 版本尚未发布。
