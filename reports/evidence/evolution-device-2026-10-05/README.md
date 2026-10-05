正式证据来自 evolution_device_probe.py 的三条隔离存储流程，先搭建持池守恒的定向商店/装备/教学场景，再走A/B/C down/up/tick/state。summary.json source_stable_during_probe=true，3条trace共356条记录（326个输入事件＋30条注记），28快照。

PNG由 evolution_device_capture.js 用当前Canvas渲染器回放这些screen数据，精灵只读取本地8807；不新增游戏动作。visual.json绑定原生240×320 PNG/快照/源码哈希、零浏览器错误。主代理目视evolution-overview及关键详情；PC画面不等于真机或真人定时验收。

archive保留首版菜单重叠/卡外文字以及源变化期间捕获的失败记录；不能用作最终通过。完整详情通过长按C和A/B分页，紧凑菜单只画单行标签。

复现：python3 tools/acceptance/evolution_device_probe.py --out .build/evolution-device；NODE_PATH=<已安装Playwright的node_modules> node tools/acceptance/evolution_device_capture.js .build/evolution-device/snapshots .build/evolution-device-png。工具代码在仓库内，不使用archive/generate.py。
