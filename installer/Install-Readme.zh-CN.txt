南枫转写 Windows v{{VERSION}} 安装说明

安装步骤：
1. 请先完整解压 ZIP 压缩包，不要直接在压缩包内运行安装程序。
2. 双击 {{SETUP_EXE}}。
3. 默认按当前用户安装到 %LOCALAPPDATA%\Programs\{{APP_NAME}}。
4. 安装程序会创建开始菜单快捷方式，并可选择创建桌面快捷方式。

使用说明：
- 这是 Windows 可点击安装版，不是便携版。
- 每个 Whisper 模型首次使用时下载一次，之后会从用户模型缓存长期复用。
- GPU 运行库不可用时，请在软件内选择“CPU 稳定”模式。
- 当前安装包未进行商业代码签名，Windows 可能显示未知发布者或 SmartScreen 提示。

卸载方法：
- 可在 Windows“设置 > 应用 > 已安装的应用”中卸载“南枫转写”。
- 卸载软件不会自动删除已下载的 Whisper 模型缓存。

English reference:
1. Extract the ZIP package completely, then run {{SETUP_EXE}}.
2. This is the clickable Windows installer, not a portable package.
3. Whisper models are downloaded once and reused from the persistent user cache.
4. Use CPU Stable mode when the required GPU runtime is unavailable.
