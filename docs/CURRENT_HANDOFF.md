# 当前交接：2026-10-20 v1.0.12 已发布

事实与验证见[当前状态](PROJECT_STATUS.md)、[合同](CONTRACTS.md)、[索引](contract-registry.json)、[审计](contract-audit.md)与[发布收据](release-v1.0.12.json)。

- 标签与应用源码：`c2b0fbc8e6fde2aeb7f5abdc8fc56e13b38f33bb`；实际冻结应用输入对应`48bf067a070d31677b6c6f9299dcb79ff2091d52`，后续提交只修复源码/发布收据测试分层，应用输入指纹完全相同。
- [正式Release](https://github.com/nanzhufeng/NanfengTranscriber-Windows/releases/tag/v1.0.12)仅一个Setup EXE，167172031字节、NotSigned。短路径产物`D:/ReleaseUploads/NanfengTranscriber-Windows-v1.0.12/NanfengTranscriber-Windows-v1.0.12-Setup.exe`；摘要及远端核验见收据。
- 181项完整回归、34项发布合同、14项Windows发布检查通过；846项负载哈希、隔离安装/启动/卸载、真实播放与显式source venv的PowerShell5验证通过。未复验默认环境真实离线模型推理、真实付费API或用户正式AppId升级。
- 直接大文件上传因EOF和超时转为20片草稿传输；Actions在GitHub内校验、按序重组同一EXE并清理分片后正式发布，未重编译。证据`.runtime/qa/release-v112/`，运行[组装任务](https://github.com/nanzhufeng/NanfengTranscriber-Windows/actions/runs/39398208494)。
- 保留其他任务未跟踪`docs/ui-design-baseline.md`，不修改用户数据、凭据和模型；固定复用build/dist_release_current，不移动已验证标签。

源码入口[启动修改版](../启动最新界面_Windows.bat)。

发布后10项合同回归通过；未发布源码的负例夹具同步切换旧收据链接，真实发布门禁仍保持严格，未修改应用代码或产物。
