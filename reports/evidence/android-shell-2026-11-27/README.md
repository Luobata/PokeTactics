# 安卓壳 App 真机 E2E · 2026-11-27

设备：Dora 云真机 Pixel 9a / Android 15 / Android System WebView 157；App 1.0.132（提交 f1ce0d0）。
服务：常驻预览（跟随 `feat/android-shell`）`https://10.4.63.169:8821/play`（VPN 地址），APK 来自 `http://10.37.30.198:8820/app/PokeTactics.apk`。

命令（结果 PASS，见 `summary.json` 的 `checks`）：

```sh
python3 tools/android/shell_e2e.py --serial <dora-adb> --url https://10.4.63.169:8821/play \
  --apk-url http://10.37.30.198:8820/app/PokeTactics.apk --download-page http://10.4.63.169:8820/app \
  --out reports/evidence/android-shell-2026-11-27
```

| 文件 | 内容 |
|---|---|
| `01-download-page.png` | 手机 Chrome 打开下载页（修正后的手机宽度版本） |
| `01b`–`01k` | 手机上手动走通的安装路径：Chrome「无法安全地下载文件 → 保留」「文件可能有害 → 仍然下载」、Play 保护机制询问、下载完成、「不允许安装未知来源应用 → 设置」、「允许来自此来源的应用」、下载内容、「要安装此应用吗？」、「已安装应用」、打开 App（手机上 APK 的 SHA-256 与服务器一致；此段不在脚本里） |
| `02-error-page.png` | 默认局域网地址在云真机上不可达：15 秒后「连不上游戏服务器」+ 重试 / 设置地址 |
| `03-settings.png` | 隐藏设置页填入 VPN 地址 |
| `04-game-opened.png` | 全屏竖屏打开游戏，无状态栏 / 导航栏 |
| `05-forced-landscape.png` | 系统强制横屏时 App 仍为竖屏（信箱显示） |
| `06`–`14` | 一整回合：海克斯 → 商店 → 招募 → 上场 → 开战 → **战斗中按返回弹「退出游戏？」（`12`），战斗未被跳过** → 战果 → 第 2 轮 |
| `15`–`17` | 返回键：商店抽屉打开 → 返回关闭抽屉 → 再返回弹「退出游戏？」 |
| `18-swipe-once-bars.png` | 单次边缘侧滑只唤出系统栏（随后自动隐藏），不返回 |
| `19`–`20` | 两段式边缘侧滑：先关商店抽屉，再次弹「退出游戏？」 |
| `21-exited.png` | 最后「退出」真正退出到桌面 |
| `screenrecord-360p.mp4` | 脚本全程录屏（360p 转码；1080p 原片在开发机 `~/.local/share/poketactics-preview/evidence/`） |
| `logcat.txt` | App 自身日志（`back -> …`、`exit dialog …`、`vibrate […]`、insets） |
| `summary.json` | 每项断言与数据 |
截图为 256 色量化 PNG（原分辨率 1080×2424）。
