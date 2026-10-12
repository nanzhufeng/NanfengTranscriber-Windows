# 南枫转写 Windows：项目协作合同

默认简体中文，称呼“南烛枫”。这是本地优先的批量音视频转写工具。

## 事实源与接手

1. 先读 [当前状态](docs/PROJECT_STATUS.md)、[当前合同](docs/CONTRACTS.md) 和 [架构入口](docs/context.md)。需要恢复执行细节时再读 [交接](docs/CURRENT_HANDOFF.md)。
2. 当前用户指令、可验证代码与当前测试优先；历史记录仅是证据，不重新定义当前行为。版本身份由 `app/assets/product.json` 唯一维护。
3. Git 先看范围/数量或 `diff --stat`，再读限定文件；保护未提交改动。不得用 reset、clean、stash 制造干净状态。

## 实现与安全

- 保持工作台与批量队列功能；表格默认居中，状态文案和颜色读取真实结果。
- 模型目录由 `app/model_modes.py` 拥有；旧模型名称用于兼容，不新增为可选项。
- 推理、输出路径、已有结果检查和设置持久化遵守当前合同；先复用唯一所有者，不在 UI 再造规则。
- 重复反馈必须形成行为回归或确定性检查；不得只更新说明文字。
- 不删除用户媒体、输出、模型缓存或密钥；停止仅针对本任务拥有的进程。测试使用隔离设置、目录与受控样本。
- API 密钥和原始服务响应不得进入截图、仓库或发布资产；音频本地处理，联网润色的文字传输必须明确。
- 固定复用 `build` 和 `dist_release_current`；不按版本复制整套编译缓存。

## 验证与交付

- 本地入口：`启动最新界面_Windows.bat`；只在用户要求时生成安装包/发布。源码、构建、安装、真实媒体/API 与发布分别报告。
- 修改完成后运行 `python tools/check_project_contracts.py` 和受影响测试；交付前完整测试与相关 Windows 验证。最终 README、版本、收据更新后再跑合同门禁。
- 正式 Windows 路径是 PyInstaller + Inno；IExpress 脚本仅保留历史兼容，不用于正式发布。
- 当前界面截图仅在 README 展示；Release 正文简洁，不嵌入或附加截图。发布附件是安装 EXE 与必要校验文件。
- Windows 默认未签名发布并如实核验；其他平台不能继承该例外。交付方法路由 `develop-apps-with-nanfeng-product-standards/references/delivery-and-acceptance.md`。
- 跨端迁移从源码开始，不复用 Windows 的 EXE、BAT、DLL 探测或盘符。
