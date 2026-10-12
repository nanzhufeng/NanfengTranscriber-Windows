# 当前交接：v1.0.7 发布

目标：交付合同整理及选中效果、表头边缘修正后的 Windows 软件。事实入口见 [PROJECT_STATUS.md](PROJECT_STATUS.md)、[CONTRACTS.md](CONTRACTS.md) 和 [context.md](context.md)。

- 57 项完整测试、23 项合同门禁、编译和冻结版启动通过。
- 独立 QA AppId 安装/启动/卸载通过；784 个安装文件与冻结目录哈希一致。README 两张图来自实际安装版。
- 冻结版受控离线中文转写：45 字符，TXT/SRT，4 个有效时间段；真实用户准确率与真实 API 不在本次验证范围。
- 正式安装包 `NanfengTranscriber-Windows-v1.0.7-Setup.exe`：159,822,661 字节，SHA-256 `a964689c54c05250a3ee584d058d26735d4e3ca4afdf768c8f5e24cad26a7a7c`，NotSigned。
- 上传短路径：`D:/ReleaseUploads/NanfengTranscriber-Windows-v1.0.7/`。Release 仅上传 EXE，远端摘要可作校验；不上传 ZIP、截图或说明 TXT。
- 验收根 `.runtime/qa/release-v107/`。固定编译目录与按需运行环境保留，旧包及旧收据不改写。
- 核对远端命令：`gh release view v1.0.7 --json tagName,targetCommitish,isDraft,isPrerelease,assets`。远端读取和 Git 标签须对应本次最终提交；本地文件不能替代上传成功证据。
- 当前启动入口 `启动最新界面_Windows.bat`；后续优先验证运行中关闭窗口生命周期，债务见 [contract-audit.md](contract-audit.md)。
