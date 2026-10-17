# 当前交接：2026-10-17 v1.0.11 已发布

事实入口：[PROJECT_STATUS.md](PROJECT_STATUS.md)、[CONTRACTS.md](CONTRACTS.md)、[context.md](context.md)、[发布收据](release-v1.0.11.json)。

- 源码/标签提交：`4617e49cba8744b306ddfaba937531ceb020c1bc`；后续仅发布收据与交接更新。正式Release：[v1.0.11](https://github.com/nanzhufeng/NanfengTranscriber-Windows/releases/tag/v1.0.11)，单Setup EXE。
- 包含后台历史读写与卡片分批渲染、后台目录发现和时长探测、成功任务自动归档、两种手机版百炼模型与DPAPI密钥保护、白底框内眼睛、设置窗口拖动缩放及大小/位置记忆、流程装饰图标精简。
- 安装包：D:/ReleaseUploads/NanfengTranscriber-Windows-v1.0.11/NanfengTranscriber-Windows-v1.0.11-Setup.exe，167122881字节；SHA256 `df5ad9f6b2ed7090a75097d026088e85a63fbe1f054e40e88f64634e21e1a7a9`，Authenticode `NotSigned`。远端摘要和大小一致，标签指向上述源码。
- 116项完整测试、23项发布合同、14项Windows结构检查通过。隔离QA AppId安装/启动/卸载、845项负载哈希、原生视频帧/进度/字幕、PowerShell5既有运行时CUDA True与离线中文精确45字TXT/SRT均通过。证据`.runtime/qa/release-v111/`与`release-v111-tests-final.log`。
- 真实付费云端API、全部编码/物理DPI及用户正式AppId覆盖升级未验收；未修改用户当前安装或业务数据。README截图来自当前安装负载、隔离受控数据。
- 保留`docs/ui-design-baseline.md`其他任务未跟踪文件，不纳入提交。固定构建目录build/dist_release_current，源码入口[启动最新界面](../启动最新界面_Windows.bat)。
