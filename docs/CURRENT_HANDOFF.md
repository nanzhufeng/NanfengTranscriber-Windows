# 当前交接：v1.0.8 发布

事实入口：[PROJECT_STATUS.md](PROJECT_STATUS.md)、[CONTRACTS.md](CONTRACTS.md)。

- 修复 PS5 的 Python `-c` 引号截断；使用临时 Python 文件校验，成功/失败均清理，支持不安装依赖的 `-VerifyOnly`。
- 列表全部单行，长文件名/路径省略并保留完整悬停提示。
- 59 项完整测试、23 项项目合同检查、PS5/7 成功失败回归通过；CUDA 探测测试隔离用户级环境。
- QA AppId 隔离安装/启动/卸载通过；784 个安装文件与冻结目录哈希一致。
- 安装版实际 PS5 校验现有用户级环境通过（CUDA True）；安装版禁用网络的受控中文转写通过，45 字符、TXT/SRT、4 条不重叠字幕。未重新下载整套新环境或验证用户真实媒体/API。
- 安装包 `NanfengTranscriber-Windows-v1.0.8-Setup.exe`，159,832,691 字节，SHA-256 `1bf656557a966de52876e4591ec7a89f9055adffd80254c21162c36accd3b65f`，NotSigned。
- 上传短路径 `D:/ReleaseUploads/NanfengTranscriber-Windows-v1.0.8/`；只上传 EXE。证据 `.runtime/qa/release-v108/`，固定编译目录不复制。
- 远端独立核验：`gh release view v1.0.8 --json tagName,targetCommitish,isDraft,isPrerelease,assets`，对应最终提交与字节摘要。
- 既有 v1.0.7 不改包；未跟踪 `docs/ui-design-baseline.md` 属于其他任务，未纳入本次提交。
- 下一步优先处理运行中关闭窗口生命周期，详见 [contract-audit.md](contract-audit.md)。当前源码入口 `启动最新界面_Windows.bat`。
