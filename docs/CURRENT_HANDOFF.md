# 当前交接：v1.0.9 Windows

事实入口：[PROJECT_STATUS.md](PROJECT_STATUS.md)、[CONTRACTS.md](CONTRACTS.md)、[发布收据](release-v1.0.9.json)。

本轮完成本地历史、画面内播放器与后续视觉反馈。`app/history.py` 唯一拥有 SQLite 文稿，`app/history_ui.py` 负责历史/详情/字幕交互，`app/media_player.py` 负责画面内播放及续播设置，`app/ui_icons.py` 负责共享 SVG。`TranscribeResult` 携带独立历史快照所需元数据，完成信号幂等入库；工作台页面与 Worker 在历史切换时保留。

视频参考南枫下载 Android `6d7245e` 的真实内置播放器；Windows 下载版本身仍调用外部播放器。Desktop 交互为画面内控制、2.5秒自动隐藏、单击字幕定位、双击画面两侧10秒跳转、键盘/倍速/音量/全屏及逐源续播。文稿新排版不修改保存文字；Windows 原生右侧行尾回归已通过。

删除只清理历史快照和内部缩略图，原媒体、外部导出、模型缓存不动。用户明确移除功能审阅及三个文稿页签，原文/成稿仍独立保存。圆圈复用批量选择，全选仍限当前筛选结果。

固定缓存 `build` / `dist_release_current`；源码启动入口 [启动最新界面 BAT](../启动最新界面_Windows.bat)。本次安装包短路径 `D:/ReleaseUploads/NanfengTranscriber-Windows-v1.0.9/`，167087862 字节，SHA-256 `c8429bd3357b843a272a03dea121845eed6bbf53dbbd6f84f8d33dbed1505e16`，NotSigned。

隔离安装/启动/卸载及844个负载文件哈希通过；安装后受控H.264/AAC播放有效；PS5校验已有环境CUDA True、离线受控转写45字/TXT/SRT通过。QA隔离目录 `.runtime/qa/release-v109/`。用户真实AppId升级、真实媒体/API及所有编码未扩展验收。

`docs/ui-design-baseline.md` 为既有其他任务未跟踪文件，不纳入本次提交。后续不要覆盖或清理它；旧v1.0.8包和收据不修改。

最终92项完整测试、23项发布合同门禁通过；Release入口 https://github.com/nanzhufeng/NanfengTranscriber-Windows/releases/tag/v1.0.9 ，远端大小/摘要需在发布任务最终独立核验。

正式发布最终核验：GitHub v1.0.9 为非草稿、非预发布，仅一个安装 EXE；远端167087862字节与SHA-256和本地一致，标签应用源码 `d18b100b4598e5a79e6952509f0ad362a23366db`。本地直传因中断改用20个临时草稿分片，Actions在GitHub内逐片校验摘要、按序重组并核验原EXE后清理分片并发布，没有重新编译安装包。可恢复传输工具为 `tools/assemble_release.py` / `.github/workflows/assemble-release.yml`，仅手动触发；成功运行 `38874220893`，临时分片均已删除。主分支后续传输工具和证据提交不改变v1.0.9应用负载；勿移动已验证版本标签。远端完整元数据保存在 `.runtime/qa/release-v109/github-release.json`。
