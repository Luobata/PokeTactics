# 48 个原生技能：原版招式参考与竞技适配

当前竞技呈现版本 `web-arena-v7-roster-review`。材质、体积和制作流程以 [37 · 技能特效基础审美](37-skill-vfx-art-direction.md) 为准；本表持续维护原版参考。本版替代 v4 的象征化图标方案：先核对原版动画脚本的素材类别、运动轨迹与出场顺序，再重绘竞技画布的像素效果。大字爆炎保留已确认实现；其余 47 招重做。

## 参考依据

原版编排基于固定提交的 [pret/pokeemerald 动画脚本](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s)。下表逐招链接至实际入口行；这是源码编排核对，不宣称逐一观看了原版实机视频，也不直接复制原作图片或音频。G1–G3 的整体观察保留在 [17 · 动画参考](17-gen123-animation-reference.md)。

隐形岩和尖石攻击（岩刃）来自第四世代。本版岩钉场沿用这类视觉概念，但像素编排的可核验基础是第三世代岩石封锁、岩崩与撒菱，不把后世招式标为 G3。

## 每招映射

| 宝可梦 / 当前原生技能 | 原版参考 | 适配后的动作 |
|---|---|---|
| 妙蛙花 · 日光反哺 | [日光束（阳光烈焰）](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5437)、[终极吸取](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5814) | 花心吸收光球后射出持续亮芯光束，命中迸出光屑 |
| 喷火龙 · 大字爆炎 | [大字爆炎](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L856) | 保留已确认的火束、大字火焰与飞溅火星 |
| 水箭龟 · 双炮冲击 | [水炮](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5612) | 两个炮口持续喷出独立实体水流，翻卷边缘与螺旋白沫，厚浪面弯曲散开 |
| 巴大蝶 · 净化蝶粉 | [催眠粉](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L506)、[麻痹粉](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L482)、[治愈铃声](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7708) | 错层粉簇飘落，尾段逐渐散尽；净化星光只围绕真实接收者 |
| 雷丘 · 电流链 | [十万伏特](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L1075) | 短促错拍电击与窄电弧；额外电链只连接真实连锁目标 |
| 尼多后 · 毒刺护甲 | [溶化](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2997)、[毒针](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L816) | 身体局部压低，厚酸液流面与硬脊毒针；保护由真实事件展开光壁 |
| 尼多王 · 毒角突袭 | [毒针](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L816)、[角撞](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2423)、[角钻（尖角钻）](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2465) | 圆润锥体沿轴旋转前刺，弧形冲击面张开，毒屑曲向散开 |
| 皮可西 · 月光祝福 | [月光](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L3365)、[祈愿](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L8155) | 淡光下落与回复星屑，避免巨型月亮图标 |
| 胖可丁 · 治愈歌声 | [唱歌](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2550)、[治愈铃声](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7708) | 流动音符抵达敌人，真实治疗对象出现铃声星屑 |
| 霸王花 · 芳香花域 | [芳香治疗](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L4137)、[花瓣舞](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6794) | 花瓣螺旋与轻盈香气，真实回复独立表现 |
| 风速狗 · 炽焰守护 | [火焰轮](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L660) | 主次卷焰绕身聚拢后向目标卷出，接触后分解成余烬 |
| 胡地 · 瞬移念力 | [瞬间移动](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2769)、[精神强念](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L4733) | 施法者纵向拉伸，落点两侧念力弯面挤压，尾端收缩断裂 |
| 怪力 · 四臂连击 | [连续拳](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L1007)、[音速拳](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L3125)、[十字劈](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6468) | 四个拳部发射点错拍冲击，命中处短促交叉拳痕 |
| 毒刺水母 · 毒潮屏障 | [污泥炸弹](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5962)、[溶解液](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6005) | 错拍污泥抛射，命中形成厚湿面和黏滴，随后上浮毒泡 |
| 隆隆岩 · 岩甲震波 | [地震](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2599)、[岩石封锁](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L9131) | 贴地震波、岩块突起与碎裂 |
| 呆壳兽 · 迟缓领域 | [念力](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L4716) | 目标局部调色与形变，扁平慢透镜波面收缩散尽 |
| 耿鬼 · 暗影汲能 | [影子球](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7356)、[终极吸取](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5814) | 有暗面与亮肩的影子球加速抵达，碎裂为卷烟；汲取回流只跟随真实效果 |
| 大岩蛇 · 岩钉场 | [岩石封锁](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L9131)、[岩崩](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2119)、[撒菱](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6092) | 硬平面尖石分批投落、突起与碎裂，实际场地保留贴地裂隙与错落岩钉 |
| 飞腿郎 · 扫堂飞踢 | [踢倒](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2586)、[回旋踢](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2385) | 低位扫腿弧与瞬时足部冲击 |
| 大舌头 · 救援舌 | [舌舔](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7371)、[自我再生](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7569) | 粗细渐变的软组织舌头随真实方向弯曲伸出，再连续收回 |
| 吉利蛋 · 生命脉冲 | [炸蛋](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7331)、[生蛋](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7685) | 小型蛋状投射物碎裂，友方恢复光点 |
| 蔓藤怪 · 缠根之域 | [扎根](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7836)、[藤鞭](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L1513) | 有粗细和明暗的藤根贴地生长，缠绕后回抽、散落叶屑 |
| 宝石海星 · 星光共鸣 | [泡沫光线](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2190)、[高速星星](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L530)、[自我再生](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7569) | 实心五角星与泡沫沿轨道抵达，命中后星屑与泡沫破裂 |
| 魔墙人偶 · 屏障接力 | [幻象光线](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7134)、[光墙](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5026)、[反射壁](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5066)、[屏障](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5083) | 明暗分层的念力环射向目标，真实保护对象展开透明平面 |
| 飞天螳螂 · 疾风十字 | [劈开](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L3034)、[旋风刀](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7515) | 斜向刀痕与旋转风刃，命中后尾流散开 |
| 电击兽 · 雷暴导体 | [打雷](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L4770) | 粗细分层的重雷柱从上方落下，短分叉与受压弧面强化接触 |
| 凯罗斯 · 破甲夹击 | [夹住](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L1841) | 两个真实钳口发起相向切击，交汇处短促命中闪 |
| 肯泰罗 · 蛮力冲阵 | [猛撞](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L760) | 前冲速度线与近身撞击，落点碎尘 |
| 拉普拉斯 · 冰霜庇护 | [冰冻之风](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2228)、[冰冻光束](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5351)、[自我再生](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7569) | 三轨连缀冰晶形成冰束，接触短暂持续后碎冰弹开 |
| 化石翼龙 · 悬崖掠袭 | [翅膀攻击](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6170)、[岩崩](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2119) | 双翼短痕接落石碎裂 |
| 大竺葵 · 清露花幕 | [花瓣舞](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6794)、[芳香治疗](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L4137)、[光合作用](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5913) | 叶片与花瓣交错上旋，清露散落；恢复光环围绕真实患者 |
| 火暴兽 · 烬火喷发 | [喷火](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L3805) | 一块主热岩带次级熔块抛起、错拍坠落，撞出炽热碎屑 |
| 大力鳄 · 潜流锁阵 | [潮旋](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6365)、[冲浪](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6304) | 厚实旋转水体与翻卷浪唇，泡沫水滴离心甩出 |
| 大尾立 · 警戒尾击 | [摔打](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L1489)、[摇尾巴](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L1195) | 圆厚尾部沿弯曲轨迹拍落，局部压缩后扫开尘屑 |
| 猫头夜鹰 · 守夜安抚 | [起风](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6152)、[唱歌](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2550)、[治愈铃声](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7708) | 有厚度的螺旋风带与短音符，净化反馈跟随真实接收者 |
| 电灯怪 · 灯塔接力 | [萤火](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L3896)、[电磁波](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L1124) | 身体局部蓄光与细电波，真实回复与回能分别作用于实际友军 |
| 电龙 · 雷光信标 | [电磁炮](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7203) | 深色电球压扁后撕成绕身电弧，与纵向落雷分开编排 |
| 沼王 · 泥沼锚定 | [掷泥](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5220)、[浊流](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L8601) | 厚泥团低抛后铺成贴地泥浪，黏湿碎块落下并收散 |
| 太阳伊布 · 弱点预见 | [预知未来](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L4750) | 两道错位预见波面形成剪切感，真实命中时局部压缩与闪光 |
| 月亮伊布 · 月影护幕 | [奇异之光](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2051)、[反射壁](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5066)、[屏障](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5083) | 暗光球抵达后反弹散开，真实守护展开蓝色反射壁 |
| 大钢蛇 · 钢尾震退 | [铁尾](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7251) | 有金属明暗面的宽尾击横扫，接触形成短压面与金属碎屑 |
| 千针鱼 · 毒针散布 | [飞弹针](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L702)、[撒菱](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6092) | 三枚有硬脊暗底的毒针错拍弧线飞行，实际落点散开钉刺 |
| 巨钳螳螂 · 交叉弹拳 | [金属爪](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7291)、[音速拳](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L3125) | 双钳交叉金属切痕与短促拳压 |
| 赫拉克罗斯 · 破角突击 | [超级角击](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6109)、[角钻（尖角钻）](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2465) | 有阴影体积的角钻与旋转螺纹，厚冲击面压入后舒展碎裂 |
| 刺龙王 · 潮龙贯流 | [水炮](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L5612)、[龙息](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L4931) | 粗细起伏的旋流水柱与弯曲浪面，龙属性追加只跟随真实侧击 |
| 战舞郎 · 旋转扫钉 | [高速旋转](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L3346) | 绕身旋转残影、横向尘线与近身撞击 |
| 幸福蛋 · 幸福合唱 | [治愈铃声](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L7708)、[喝牛奶](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L3297) | 小铃波与跳动音符形成合唱节奏，真实回复伴随环绕光与上升星光 |
| 班基拉斯 · 岩崩壁垒 | [岩崩](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L2119)、[沙暴](https://github.com/pret/pokeemerald/blob/731ad5bfd6e6f265508d0efcca0ba42f9dcf5881/data/battle_anim_scripts.s#L6345) | 错落岩块与贴地砂流，碎岩保护墙随真实事件显示 |

## 演出约束

- 双炮冲击的两个水流从真实炮口发射；日光反哺从花心吸光后放出持续光束。命中后的短暂持续段与水花／光屑分层，避免弹体贴在目标身上不动。
- 原生保护、其他事件保护与持续护盾共用透明的光墙／反射壁平面；持续时间来自实际盾值和守护记录。回复使用环绕恢复光和上升主星；每条实际正值 `regen` 只绘制一次恢复材质与数字，原生技能身份通过事件归属核验。
- 念力类用身体挤压与局部调色；瞬移念力施法者短暂拉伸，毒刺护甲参考溶化压低身体。真实正伤害触发约 55ms 的压缩停顿后回弹，在 240ms 内结束；冻结和死亡优先，不冻结世界时钟。
- 主施法仍按现行规则伤害敌人。追加伤害、吸能回流、回复、保护和移动只消费经过 cast_index 校验的真实事件；不得借参考招式添加范围、状态或伤害。岩钉持久地形由实际场地记录控制。
- 接触阶段 0.22s、消散窗口合计 0.8s；有限演出时间不改变 release / impact、行动恢复或下一次施法。精神类没有实体飞行物时，允许飞行特效层为空，完整演出由身体动作构成。
- 部件锚点跟随蓄力动作，发射后固定在实际发射位置。身体缩放同步变换脚底与发射附件；缓存图像不原地着色。血条、数字和 HUD 最后绘制。

## 工具与验证

试玩新战斗、竞技实验室、编辑器、训练场与竞技导出共用呈现模块。实验室和编辑器显示原版参考名称；`move_references.py` 是完整映射源。已生成历史回放图片保留原版本。

本次覆盖全 48 招四阶段、17 招动态短片和五种 6 对 6 场景；检查真实接触时点、侧击、冻结、死亡、倒放重采样、发射锚点及缓存不变性。结果见 `reports/original-move-reference-2026-10-07.md`。经典设备呈现未改动；普通攻击和技能机攻击继续沿用其既有演出。
