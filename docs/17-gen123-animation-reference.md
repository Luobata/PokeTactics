# 17 · G1–G3 招式动画编排参考

状态：**源码参考与适配建议，2026-10-05**。本文核对的是 pret 项目的动画
脚本，不是观看原作动画后的视觉评价；未运行原作、读取 ROM，或提取其
贴图与音频。下文“观察”仅描述脚本指令与先后关系，“建议”是本项目的
设计判断，不代表演出已经实现、视觉验收通过或设备性能达标。

源码基准均固定到以下提交，表内链接使用对应文件的实际行号：

- G1：`pret/pokered`，`d2704a63c26f9ba046ade877445216b3de0519a4`，
  [data/moves/animations.asm](https://github.com/pret/pokered/blob/d2704a63c26f9ba046ade877445216b3de0519a4/data/moves/animations.asm#L207-L233)。
- G2：`pret/pokecrystal`，`5beda23ffa505f62e1dad7e3d7c214d1737b3358`，
  [data/moves/animations.asm](https://github.com/pret/pokecrystal/blob/5beda23ffa505f62e1dad7e3d7c214d1737b3358/data/moves/animations.asm#L918-L942)。
- G3：`pret/pokeemerald`，`731ad5bfd6e6f265508d0efcca0ba42f9dcf5881`，
  [data/battle_anim_scripts.s](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5612-L5657)。

## 1. 八只角色与当前招式

名称和 `move_id` 对齐本项目 `build_templates()` 的读取结果。属性机制、
角色档案的战斗原语与招式演出分开：不能因为参考了影子球、岩崩或泰山
压顶，就把当前舌舔、地震、破坏光线改名或改成另一种伤害行为。

| 角色 | 当前招式 | 源码编排观察 | 本项目适配建议 |
|---|---|---|---|
| 6 喷火龙 | 53 · 喷射火焰 | [G2](https://github.com/pret/pokecrystal/blob/5beda23ffa505f62e1dad7e3d7c214d1737b3358/data/moves/animations.asm#L918-L942) 沿路径每隔 2 个等待单位生成下一团火；[G3](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6311-L6342) 连续生成火焰并在中途加入目标震动。 | 火团前后相接，源端窄、末端张开；命中层用短火舌和少量上扬余烬，与飞行主体分开。 |
| 9 水箭龟 | 56 · 水炮 | [G3](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5612-L5657) 将成对水流粒子与独立水花交替编排。 | 双股流束、椭圆水珠和横向水花；水花只在目标处出现，不把火焰改蓝色充当水炮。 |
| 3 妙蛙花 | 76 · 日光束 | [G2](https://github.com/pret/pokecrystal/blob/5beda23ffa505f62e1dad7e3d7c214d1737b3358/data/moves/animations.asm#L1212-L1236) 分聚能和发射分支；[G3](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5443-L5508) 先吸收周围光球，再连续放出光束对象。 | 叶光向花心收拢，再发窄亮芯光束；不画成飞叶快刀，不引入原作两回合机制。 |
| 26 雷丘 | 85 · 十万伏特 | [G3](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L1075-L1104) 错开三次电击，随后加入目标周围电火花。 | 折线主电弧配短分叉，命中后出现小电爪；辅助电弧不表示多次真实伤害。 |
| 65 胡地 | 94 · 精神强念 | [G2](https://github.com/pret/pokecrystal/blob/5beda23ffa505f62e1dad7e3d7c214d1737b3358/data/moves/animations.asm#L2972-L2984) 使用波对象与色相变化；[G3](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L4733-L4748) 配合目标震动、缩放与背景切换。 | 薄椭圆波、短暂挤压与瞬移残影；环内部留空，目标轮廓保持可见。 |
| 94 耿鬼 | 122 · 舌舔 | [G2](https://github.com/pret/pokecrystal/blob/5beda23ffa505f62e1dad7e3d7c214d1737b3358/data/moves/animations.asm#L2634-L2639) 使用专用舌舔对象；[G3](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7371-L7378) 同时轻震目标。 | 弯曲舌弧快速伸出、接触、收回，暗紫残影作为辅助层；不替换为飞行影子球。 |
| 76 隆隆岩 | 89 · 地震 | [G1](https://github.com/pret/pokered/blob/d2704a63c26f9ba046ade877445216b3de0519a4/data/moves/animations.asm#L710-L713) 连续震屏；[G3](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2599-L2607) 使用水平震动与背景色变化。 | 从脚下起裂，土浪沿地面传播，碎石低幅弹起；不画成天降陨石，也不随意扩大真实受击范围。 |
| 143 卡比兽 | 63 · 破坏光线 | [G1](https://github.com/pret/pokered/blob/d2704a63c26f9ba046ade877445216b3de0519a4/data/moves/animations.asm#L553-L560) 向内聚球后发光束；[G3](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L8362-L8410) 连续发射光球并安排双方震动。 | 身体先稳住重心，口部聚能后发宽束，用亮芯、外缘和后坐力区别于日光束；泰山压顶只可借鉴身体动作。 |

## 2. 六条编排原则

1. **把招式拆成聚能、传播、命中、消散。** G1 大字爆炎已经把火束、
   星形与火柱串联；G3 则分为火环与五个射向的火焰。
   [G1 编排](https://github.com/pret/pokered/blob/d2704a63c26f9ba046ade877445216b3de0519a4/data/moves/animations.asm#L933-L939)、
   [G3 编排](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L856-L902)。
   建议各阶段有自己的关键姿态；时间服从本项目的 start、release、impact、
   recover_end，不为凑满原作等待时长而拖慢结算。参考大字形状也不意味着
   将喷射火焰的招式名称替换为大字爆炎。

2. **移动主体与命中层独立，多层 sprite 错开发射。** 水炮的水流与水花
   是可直接参考的拆分。草系的另一个例子是 G3 飞叶快刀先散叶，再用
   相反波幅发出两片刀叶，之后震动目标。
   [飞叶快刀编排](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6832-L6870)。
   建议分开源端、主体、尾迹和命中层；错峰产生连续感，避免同帧把全部
   粒子铺满。此例用于学习编排，不替换妙蛙花当前的日光束。

3. **先区分形状，再区分颜色。** 建议八种主轮廓分别为火舌、双水流、
   窄光束、折电、椭圆波、舌弧、地裂、宽光束。G2 影子球的主体飞行后
   接烟团，和精神强念的波对象并非同一种表现。
   [影子球编排](https://github.com/pret/pokecrystal/blob/5beda23ffa505f62e1dad7e3d7c214d1737b3358/data/moves/animations.asm#L4512-L4520)。
   验证时可隐藏名字、降低色彩后看短片，检查是否仍能认出招式；不能仅
   用“颜色不同”判断角色演出已区分。

4. **只借鉴色板变化的作用，不照搬全屏闪烁。** G1 精神强念含长闪屏
   与波动，G2 十万伏特含反色效果。
   [G1 精神强念](https://github.com/pret/pokered/blob/d2704a63c26f9ba046ade877445216b3de0519a4/data/moves/animations.asm#L736-L739)、
   [G2 十万伏特](https://github.com/pret/pokecrystal/blob/5beda23ffa505f62e1dad7e3d7c214d1737b3358/data/moves/animations.asm#L1256-L1266)。
   建议改为目标局部的单次亮度脉冲或短色边；HUD、血条和非目标棋子保持
   稳定。多人同时施法时，不把每条技能轨的反色或震屏直接相加。

5. **身体发力与命中节拍配合。** G3 泰山压顶先下沉、滑移，再出撞击、
   震动目标并归位；G2 岩崩按间隔混用大小岩块。
   [泰山压顶编排](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L597-L621)、
   [岩崩编排](https://github.com/pret/pokecrystal/blob/5beda23ffa505f62e1dad7e3d7c214d1737b3358/data/moves/animations.asm#L1415-L1436)。
   建议借用预备动作、后坐力、大小错落和恢复动作：卡比兽用稳定重心与
   发射后坐力，隆隆岩用下压启动地裂。身体视觉位移不改变棋盘占位，
   地裂和碎石也不增加命中目标。

6. **同屏时保留主体和命中点，先削减装饰。** 建议将主轮廓、目标和
   血条列为优先信息；超预算时先减少尾迹、火星、尘埃，不能丢掉致命
   弹道或将命中提前。每招 6–12 个可见辅助粒子可作为一次试验的起点，
   不是新全局上限，也不是 ESP32 已测能力。应在现有总预算内测试八只
   角色同时施法，再按耗时和可读性调整。

## 3. 本项目适配边界

- **参考节奏和组织，资源另行制作。** 不直接复制原作坐标、tile、音效
  或整段等待值。脚本中的等待数、对象数和调色板系数是来源参数；本文
  没有把它们解释成本项目毫秒数或画面尺寸。已有角色素材的来源与资源
  合同见 [16 · 动画、美术资源与可移植清单](16-animation-art-contract.md)。
- **模拟事实与视觉表现分开。** 动画消费已产生的事件，不改变伤害、
  命中、范围、死亡、状态和游戏 RNG。视觉上的多个火团、电弧或水珠
  仍可能对应一次伤害；数字、HP 和死亡按权威 impact 显示。
- **以当前演出时钟为准。** 传播阶段嵌入已有 release→impact；窗口短
  时优先保证发射与命中可辨，不能让投射物在目标死亡后才到达。需要
  调整演出时间时应经过现有事件编排层，倍速、跳过和倒放不能各改一套。
- **以 240×320 同屏战斗为目标。** 保持像素轮廓、图层顺序和血条可读；
  原作单次招式的全屏背景切换、长震屏不能直接叠到多人战斗。胡地闪现
  等现有战斗原语仍由本项目决定，不能据参考脚本添加新机制。
- **验收仍需执行。** 应分别检查八招短片、两队密集交战、同刻多招、
  致命命中、0.5×／1×／2×与跳过。视觉识别、遮挡、帧耗时及设备资源
  都需留实际证据；本文的源码核对不代表这些检查已经通过，也不代表
  C 绘制或 ESP32 真机移植完成。
