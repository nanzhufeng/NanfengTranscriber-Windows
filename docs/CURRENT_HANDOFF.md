# 当前交接：2026-10-20 v1.0.12 发布进行中

事实与验证结果见[当前状态](PROJECT_STATUS.md)，稳定行为见[合同正文](CONTRACTS.md)，路径和文档角色见[索引](contract-registry.json)，冲突/剩余债务见[审计](contract-audit.md)。不在本页复制整份状态和发布收据。

- 工作区基线`cb31eed57a5b6099d865d2a679df03e37729abaa`，本轮未提交；产品元数据为1.0.12，正在冻结和发布；GitHub当前正式版仍为1.0.11。
- 2026-10-20全面排查：修复进程管道堵塞、QThread析构死锁、全局Combo过滤器累积、历史/调用记录大列表与长稿、GUI磁盘写入/路径预检/日志/声音阻塞。设置写入失败保留修改并支持重试；关闭等后台实际完成。新增settings_io/ui_io/dependency_install/background_feedback职责模块，不改变存储身份或模型协议。
- 并发保护：预检核对队列task_id、导入/运行互斥；历史导航合并与迟到结果取消，取消关闭恢复完整编辑稿与媒体。根因、测量和真实服务边界见审计，日志在.runtime/qa/freeze-audit-20261020/。
- 2026-10-20新增：移除云端启动二次确认，保留Key检查和设置上传/计费说明；不调用真实API，不打包。
- 同日新增调用记录：`app/invocations.py`拥有独立安全元数据SQLite与手机估价/文件汇总，`app/invocation_ui.py`拥有后台查询入口和列表，`cloud_asr.transcribe_cloud`在实际请求完成/失败后记录、取消不记；队列UUID在重试时保留。手机来源SHA见C03，轻量源码副本与验证日志在`.runtime/qa/call-records-20261020/`。未打包、安装、发布或调用真实付费API。
- 2026-10-18运行时`MainWindow._start`在GPU转CPU时改用dataclasses.replace更新计算模式，保留已确认云端Key/恢复目录和其他选项；新增隔离混合队列回归先红后绿。model_modes.py仅docstring澄清，无模型ID、默认值或兼容映射改变。
- 文档登记C01–C12；工具仍用唯一入口tools/check_project_contracts.py，新增文档角色/完整性、源码符号、模型表、状态版本/发布源与收据摘要核对及负例。
- 旧v1.0.6审计保存在docs/history/contract-audit-v1.0.6.md，不恢复其旧债务结论为当前事实。原Markdown快照、代码指纹和红绿/完整回归证据位于.runtime/qa/contracts-20261018/。
- 不改真实数据、密钥、模型、已发布收据、旧DPI/性能资产、安装脚本和旧兼容入口；保留其他任务原有未跟踪docs/ui-design-baseline.md。
- 最终Windows原生单进程180项完整测试通过42.237秒，exit=0；34项合同门禁及BAT检查通过。测试中所有异步窗口/任务需排空再清理夹具；悬停用Qt合成事件验证，避免物理桌面鼠标干扰。原生Combo实际Show晚于showPopup返回，生命周期过滤器必须跟随Show/Hide。
- 收口后按用户下一项任务继续；不主动打包或重发。用户要求交付新包时才递增版本并重做冻结与安装验收，不能说v1.0.11已含本轮修正。

源码入口[启动修改版](../启动最新界面_Windows.bat)。

发布阶段证据：`.runtime/qa/release-v112/`。846项负载哈希、隔离QA AppId安装/启动/卸载、真实视频帧与进度、PowerShell5显式既有source venv CUDA True已通过。默认冻结版独立环境及模型缓存当前缺失，未复验真实离线推理，不借用v1.0.11历史结论；未调用付费API。已生成短ASCII路径安装包，Authenticode NotSigned；发布完成后再登记远端摘要与源码提交。
