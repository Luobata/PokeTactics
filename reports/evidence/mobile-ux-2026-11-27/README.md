# 手机交互打磨 · 证据（2026-11-27）

问题清单：[reports/mobile-ux-audit-2026-11-27.md](../../mobile-ux-audit-2026-11-27.md)；实现与结构：[docs/74](../../../docs/74-mobile-ux-polish.md)。
设备：Dora 云真机 Pixel 9a / Android 15 / WebView 158（1080×2424，DPR 2.625，视口 411×865）。截图已缩到 360px 宽，不含地址与设备信息。

| 目录 | 内容 |
|---|---|
| `compare/` | 改前（main 1.0.132，审计时实拍）/ 改后（分支 1.0.139）同视口对比，文件名是审计编号：H1 商店盖住备战席（含 360×731）、H2 页头与菜单、H3 触屏拖拽、H4 长按选字、H5 吐司、M1/M2 操作条与招募、M5 战斗弹窗、M6 结算扣血、M7 海克斯、M9 大屏 |
| `e2e/` | 壳 App 真机 E2E（`tools/android/shell_e2e.py --tether-port 8830`），28 项检查全部通过：`summary.json`（`checks`）、`logcat.txt`（壳 App 日志）、逐步截图 |
| `desktop/` | 桌面 1280×760、1440×900：同一种子同一局面 main 与分支并排，差异像素 0.00% |

E2E 命令（分支预览服务在本机 8830）：

```sh
python3 tools/android/shell_e2e.py --serial <adb-serial> --apk-url http://127.0.0.1:8830/app/PokeTactics.apk --tether-port 8830
```

这次云真机到开发机 VPN 地址丢包严重（ping 80% 丢包），经 VPN 的三次运行分别卡在页面脚本、招募请求和上场请求上（服务端响应约 0.1s），
所以改用 `--tether-port`：WebView 的 DevTools 端口转发经 adb 到本机服务，不经过 VPN。录屏（95 MB）留在本地，未入库。
