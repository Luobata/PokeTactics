# 真机 E2E 证据（2026-11-27）

设备：Dora 云真机 Google Pixel 9a · Android 15 (SDK 35) · Chrome 157.0.8103.78 · 1080x2424。
脚本：`tools/acceptance/android_e2e.py`（docs/72 §5）。截图为原图（1080×2424）缩小一半；直连截图裁掉了含内网地址的 Chrome 地址栏，summary.json 中的内网地址与设备序列号已替换为占位符。录屏 `screenrecord.mp4` 体积较大，未入库。

| 运行 | 命令 | 结果 | 用时 |
|---|---|---|---|
| tether-install | `android_e2e.py --port 8830 --phone-port 8844 --install`（本分支服务） | PASS | 50.8 s |
| direct-service | `android_e2e.py --via direct --url http://<dev-vpn-ip>:8820/play`（常驻预览服务，main） | PASS | 19.2 s |

## tether-install 关键断言

- 一整回合：选海克斯 → 商店招募（金币 7→6）→ 备战席 → 棋盘（人口 0/4→1/4）→ 开战 → 战果「回合失利」→ 第 2 轮。
- 战斗中 Wake Lock：True；关闭战斗后已释放：True。
- Service Worker：active，接管页面 True，缓存 pt-shell-868bfe2d8f17, pt-media-4dde0d8261ca。
- 清单：display=fullscreen，orientation=any，图标 3 个；Chrome 判定可安装：True。
- 震动经应用路径调用成功：True；音频已解锁：True（AudioContext running）。
- 安装：Chrome「安装应用」对话框 → 桌面「添加到主屏幕」→ 桌面新图标 → 打开后 display-mode=fullscreen，视口 [411, 923] = 屏幕 [412, 924]，`com.android.chrome/org.chromium.chrome.browser.webapps.WebappActivity`。
- 页面错误：0 条。

## direct-service

- 手机经网络（VPN 地址）直接打开常驻预览服务 :8820，完成同一整回合，页面错误 0 条；非安全上下文（http + 内网 IP），因此无 SW / Wake Lock，符合预期（docs/72 §3）。
