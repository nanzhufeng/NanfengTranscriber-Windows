# 当前交接：v1.0.10 Windows

事实入口：[PROJECT_STATUS.md](PROJECT_STATUS.md)、[CONTRACTS.md](CONTRACTS.md)、[发布收据](release-v1.0.10.json)。

本轮优化播放器三段双击、字幕固定/居中、圆角/橙色/柔和阴影及倍速居中，整理文稿和关闭入口。确认界面线程播放位置同步写盘会阻塞，改为单后台写者合并位置/音量保存；拖动75ms合并，松手立即跳转；字幕同文不重复排版，阴影按文字/尺寸/DPI缓存。

99项完整测试、23项发布合同和14项Windows交付检查通过。固定缓存build/dist_release_current；同负载独立QA AppId隔离安装/启动/卸载通过，843个文件逐一哈希匹配；安装后视频帧/进度/字幕有效，PS5环境验证CUDA True、离线受控中文转写45字并生成TXT/SRT。证据 `.runtime/qa/release-v110/`。

短路径安装包 `D:/ReleaseUploads/NanfengTranscriber-Windows-v1.0.10/NanfengTranscriber-Windows-v1.0.10-Setup.exe`，167080658字节，SHA-256 `0baaf1d7b5710c264e03eb5d84076f712509eeb7c1234a6a8f4ae59b0261c5b3`，NotSigned。[v1.0.10](https://github.com/nanzhufeng/NanfengTranscriber-Windows/releases/tag/v1.0.10) 已正式发布，远端仅一个Setup EXE，大小和SHA-256已核对一致；应用源码/标签 `1ff18797d9df585e2ede68a386bfacdb206d181d`。

未验证正式AppId覆盖用户安装、真实媒体准确率/API及全编码；持续未响应未复现，缩放/全屏仍有短暂绘制延迟。用户真实媒体、模型、设置和凭据不提交。`docs/ui-design-baseline.md`是其他任务原有未跟踪文件，保留不纳入。旧版本包/标签/收据不修改。

传输复用 `tools/assemble_release.py` 和手动Actions，在草稿中校验分片、重组同一安装包、核对整体摘要、清理分片后正式发布。本次Actions `38884023046` 成功，20个临时远端分片已清理。
