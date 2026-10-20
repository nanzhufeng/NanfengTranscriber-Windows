> 历史布局资产：现有 manifest 的哈希检查证明旧资产完整，不证明现行软件 的多 DPI/多显示器表现。现行规则见 [CONTRACTS.md](../../../docs/CONTRACTS.md)，当前截图见仓库 README；重新生成基线是独立验收动作。

# Windows 多 DPI UI 基线

运行以下命令重新生成 100%、125%、150%、200% 四档截图：

```powershell
python tools/capture_ui_baselines.py
```

基线使用固定逻辑尺寸、固定队列内容和 Qt offscreen 渲染，用于发现布局、文字截断、控件越界和状态样式回退。它不替代真实 Windows 多显示器切换验证；发布前仍需在至少一台开启缩放的显示器上检查窗口。
