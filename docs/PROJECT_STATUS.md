# 南枫转写 Windows 当前状态

## Verified

- Last verified: 2026-10-20 +08:00
- Branch: main
- Code baseline: c2b0fbc8e6fde2aeb7f5abdc8fc56e13b38f33bb
- Product version: 1.0.12
- Published version: 1.0.12
- Release source: c2b0fbc8e6fde2aeb7f5abdc8fc56e13b38f33bb
- Release signature: NotSigned
- Status: VERIFIED — v1.0.12 Windows正式发布；单Setup EXE远端大小、摘要和标签提交均已核对。

## Current

- 修复已复现的线程析构死锁、FFmpeg/Qwen管道堵塞、全局下拉框事件过滤器累积、调用记录全量布局、历史长稿/字幕扫描，以及GUI内慢盘检查、设置写入、日志与声音阻塞。
- 导入、预检和运行入口互斥，预检核对任务身份；历史导航合并、迟到结果丢弃、编辑保护与取消关闭恢复均有行为回归。
- 设置API区下方提供按手机版字段和费用规则汇总的调用记录；已配置Key时云端转写直接开始，保留上传/计费说明和缺Key检查。
- [CONTRACTS.md](CONTRACTS.md)为唯一正文，[索引](contract-registry.json)关联所有者和回归，[审计](contract-audit.md)保留根因、测量及剩余边界。

## Tests

- 本轮Windows原生Qt单进程完整181项测试通过，43.586秒，进程exit=0；34项发布合同门禁、14项Windows发布检查与BAT启动检查通过。
- 冻结元数据与源码一致；隔离QA AppId安装、启动、卸载通过，846项应用负载逐文件哈希一致。真实视频帧、进度与冻结版对应时间字幕通过，README使用当前构建的受控数据页面截图。
- 安装负载内PowerShell5脚本通过显式选择既有source venv验证，CUDA True；不等同于默认独立环境首装或模型推理通过。
- 发布证据在`.runtime/qa/release-v112/`；卡顿复现与性能测量在`.runtime/qa/freeze-audit-20261020/`及审计所列相邻日志。旧版本收据保留，不替代本版验收。
- 源码测试允许尚未发布的版本不携带未来收据；一旦声明收据即严格校验，正式发布仍必须通过`--release`门禁。源码标签本身可运行完整回归。

## Gaps

- 当前默认独立推理环境与模型缓存缺失，本轮未复验真实离线模型推理；未调用真实付费云端/文本API。
- 用户正式AppId覆盖升级、全编码、物理多DPI、新电脑与所有底层驱动未验收；原生模型加载及当前网络调用仍可能等待底层返回，不承诺任意环境立即取消。
- 部分导出非事务、运行环境标记版本、历史失败保存的跨重启恢复及链接失败反馈等见[审计债务](contract-audit.md#保留的债务与验证边界)。

## Sync & Safety

- 保留用户媒体、输出、设置、凭据、模型、旧发布收据与历史DPI资产。
- `docs/ui-design-baseline.md`是其他任务原有未跟踪草稿，未纳入本轮提交。

## Release

- [v1.0.12](https://github.com/nanzhufeng/NanfengTranscriber-Windows/releases/tag/v1.0.12)与[发布收据](release-v1.0.12.json)：单Setup EXE，167172031字节，NotSigned。远端仅一个附件，大小与摘要匹配，标签指向上述源码。
- 后续收据、文档与测试夹具更新不改变安装负载；不得移动已核对的版本标签。

## Next

- 使用v1.0.12正式包；后续按用户反馈继续，涉及真实推理、账号或设备时独立补验相应链路。
