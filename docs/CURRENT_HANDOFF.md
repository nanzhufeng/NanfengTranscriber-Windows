# 当前交接：2026-10-17 v1.0.11 发布进行中

事实入口：[PROJECT_STATUS.md](PROJECT_STATUS.md)、[CONTRACTS.md](CONTRACTS.md)、[context.md](context.md)。旧已发布基线为v1.0.10/main f700b5a3f989e20d2faa2d876e0b706e2679bfe8；本轮待发布v1.0.11。

包含：后台历史读写与卡片批次渲染、异步目录发现/时长探测、成功任务归档、两种手机版百炼模型、DPAPI密钥保护、白底框内眼睛、设置窗口拖动缩放及布局记忆、流程装饰图标移除。

- 复用build和dist_release_current，PyInstaller+Inno成功，短路径D:/ReleaseUploads/NanfengTranscriber-Windows-v1.0.11内安装包167122881字节；SHA256 df5ad9f6b2ed7090a75097d026088e85a63fbe1f054e40e88f64634e21e1a7a9，NotSigned。
- 隔离QA AppId安装/启动/卸载、逐文件负载哈希、原生视频帧/进度/字幕、PowerShell5既有运行时和离线中文精确TXT/SRT通过。没有覆盖用户当前安装。
- 当前构建真实截图已更新README，23项发布合同和14项Windows结构检查通过；116项完整测试通过（release-v111-tests-final.log），首轮因未生成截图/收据失败已补齐。
- 下一步：显式提交本轮文件并推送main；创建v1.0.11正式Release，上传单Setup EXE并复核远端大小与摘要。上传慢可用20个8MiB草稿临时分片与已有assemble-release.yml校验组装，发布前自动移除分片。
- 真实付费云端API未调用；协议仅模拟测试；全部编码/物理DPI与用户安装覆盖未验收。

保护所有WIP；docs/ui-design-baseline.md为其他任务未跟踪文件，不纳入。构建收据见[release-v1.0.11.json](release-v1.0.11.json)。源码入口[启动最新界面](../启动最新界面_Windows.bat)。
