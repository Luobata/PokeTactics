# 统一预览、动画编辑与样片生成

网页工具默认使用 `mode=arena`：当前 48 种竞技精灵、原生技能、每方三行站位、960 × 640 战场。试玩 `/play`、整场 `/anim`、单体实验室、动画编辑器及新生成的竞技样片，共同通过 `tools/mockups/presentation_modes.py` 选择 `WebBattleRenderer`，共用真实战斗事件和演出时间轴。

## 入口

| 工具 | 当前竞技入口 | 用途 |
| --- | --- | --- |
| 调试工具总览 | `/tools` | 所有入口与文档 |
| 整场战斗预览 | `/anim?mode=arena&seed=7` | 播放、暂停、倍速、单帧、命中跳转与 PNG 导出 |
| 场景库 | `/scenarios?mode=arena` | 分件动作、岩钉击退、异常追击、属性特效、治疗防守 |
| 动作实验室 | `/animation-lab?mode=arena` | 当前角色的待机、移动、普攻、原生技能、受击与倒下样片 |
| 动画编辑器 | `/animation-editor?mode=arena` | 默认 / 调参对照、真实生命快照、预设导入导出 |
| 靶场 | `/range?mode=arena` | 转到实时实验室，始终跟随当前代码 |
| 验收入口 | `/acceptance` | 渲染版本、验证重点与报告 |

图鉴里的动作预览链接可以直接定位角色，例如 `/animation-lab?mode=arena&species=68`。

模式切换为 `mode=classic` 时保留经典 84 种角色、240 × 320 设备演出与原有规则。经典单局模拟、对照实验、设备和远征工具都有版本提示及竞技入口。旧设计稿和旧报告保留为历史材料，不代表当前试玩画面。

## 角色与动作覆盖

目录由 `GET /api/animation/characters?mode=arena` 返回，从竞技模板与原生技能生成。角色资源检查包括第一世代打包资源与第二世代普通 / 闪光 PNG。目录同时返回画布尺寸、渲染版本、动作能力矩阵、可编辑参数和分件覆盖。

怪力的四臂、雷丘的耳尾、巨钳螳螂的双钳双翼由网页分件轨道驱动；妙蛙花、喷火龙、水箭龟沿用共享分件动作。其余角色使用目录中标明的整身动作或程序化动作。可播放全部动作不等于所有角色都已完成独立关节制作。

## 调参与真实事件

预览请求为 `POST /api/animation/preview`，包含 `mode`、`species`、`kind`、`seed` 和 `settings`，并携带 `X-PokeTactics-Preview: 1`。

竞技模式支持配色、特效尺寸、粒子密度和动作幅度；它们只改变演出，不改变命中时间、伤害、技能效果和模拟结果。单体预览用独立训练场景让动作可以稳定出现：预充能、延迟对手行动、提高靶子生命或设置残血均在界面/元数据中标注，之后的攻击、治疗、击退与死亡仍由真实战斗逻辑产生。

导出的预设包含 `mode`。已有 schema 1 预设缺少 `mode` 时按经典模式解释，避免把旧参数静默套进新渲染器；新预览请求省略 `mode` 时使用竞技模式。缓存按模式、请求和源码/素材哈希隔离；第二世代 PNG 更新也会使缓存失效。

页面按需载入当前附近的帧，并限制解码缓存，切换角色/模式会取消旧请求结果。暂停后逐帧定位，网络出错可以重试。预览与目录无需创建游戏局，也不写试玩存档。

## 离线样片与检查

CLI 默认竞技模式；需要设备回归时显式添加 `--mode classic`，并选择经典池中的角色。

```bash
python3 tools/mockups/animation_showcase.py --species 68,212,26,9 --out .build/animation-arena
python3 tools/mockups/profile_range.py --species 68,212,26,9 --out reports/evidence/range-arena-current
python3 tools/acceptance/animation_acceptance.py --species all --output .build/animation-arena-contract.json
```

样片与靶场 manifest 记录模式、尺寸、渲染版本和真实动作阶段；PNG/GIF 使用同一渲染器输出。生成目录保持显式路径，历史导出不会自动冒充当前构建。

`system_acceptance.py --presentation` 会生成竞技样片并验证竞技六类动作。设备资源的 `art_manifest.py` 仍使用经典格式，单独导出到 `.build/animation-classic` 并明确列为 `classic_art_export` / `classic_art_verify`；历史版本对照脚本继续用于设备演出的历史回归。
