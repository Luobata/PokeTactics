# 15 · ESP32 通用运行时与存档边界

状态：**设计与源码借鉴记录，2026-10-04**。本轮先交付 PC 参考实现与 Demo
恢复合同；NVS、USB 设备协议、C 移植和真机掉电验证是独立阶段，不能据 PC
测试通过标记为完成。当前实现与执行结果以验收报告为准。

本文只读检查兄弟项目公开源码，未访问 `.device-backup`、私人 `.pksave`、
真实 NVS 或完整 Flash，也未修改兄弟项目。证据基准为
`ESP32-PokemonGo` 提交 `0c2292351302b9707ae0c11c09433397038ed056`；
下列借鉴文件在读取时没有工作区修改。

## 1. 结论与边界

复用的是**存储失败语义、版本分层、事务顺序、调度模式和验证方法**，
不复制 PokeWalk 的伙伴、养成、遭遇、道具、NVS 地址或 Flash 镜像格式。
通用层只处理有边界的字节、版本和提交；PokeTactics 自己负责棋子、卡池、
回合、配对和恢复后能否继续操作。

分层如下；名称是职责边界，不要求每项各建一个文件。当前实际交付为
`SessionCodec`、`SaveStore` 和 `FileBackend`；Memory Backend 仅作测试替身。
`AutoSavePolicy`、NVS 与传输层是后续边界。PC Demo 当前每次成功操作即时保存，
以共享锁串行化状态与 I/O；尚未实现设备防抖、dirty revision 调度和锁外慢 I/O。

```text
Demo / 游戏领域
  SessionCodec：字段编码、迁移、语义校验、状态发布
  Checkpoint：准备候选状态 → 持久化成功 → 发布可见状态
                 ↓
esp32_runtime（PC 参考）
  SaveStore：信封、双槽、版本选择、错误分类、导入前 checkpoint
  AutoSavePolicy：立即 / 防抖 / 强制保存，注入单调时钟
                 ↓
StorageBackend
  Memory / File（PC） → NVS（待移植）

BackupTransport（后续）
  浏览器或串口 → 设备确认 → 预备份回读 ACK → 暂存 → 重启应用/回滚
```

## 2. PokeWalk 实际可借鉴的机制

| 机制 | 代码证据 | 本项目采用的合同 |
|---|---|---|
| 保存负责初始化存储；初始化失败不擦除 | [save.c:23](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/save.c:23) | 存储生命周期不依赖 Wi-Fi；挂载失败进入可解释的只读错误态 |
| 整块快照写入并检查 commit 返回值 | [save.c:49](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/save.c:49) | 业务状态整份验证后提交，不能将多个互相依赖字段独立写成半状态 |
| EMPTY 与 ERROR 分开 | [save.h:352](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/save.h:352)、[save.c:79](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/save.c:79) | 只有真正不存在档案才允许自动进入新档；损坏、较新版本、I/O 错误不得清空或覆盖 |
| 版本与实际长度一致才解码，迁移后领域验证 | [save.c:107](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/save.c:107)、[save.c:324](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/save.c:324) | 信封检查不能替代 payload 校验；旧版本先按旧布局解码，不能给新布局伪造旧版本号 |
| 快照锁与保存锁分离 | [world.c:248](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/world.c:248) | 状态锁内取得不可变快照，慢 I/O 在状态锁外；保存串行化，防旧快照晚写覆盖新快照 |
| 写失败保留 dirty；写期间的新变化不被清掉 | [world.c:259](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/world.c:259) | 保存确认绑定具体 revision；只清除已落盘 revision 之前的脏状态 |
| 先持久化候选，再发布状态 | [world.c:301](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/world.c:301) | 开战、奖励结算等提交点必须验证保存结果，失败不能先扣费、发奖或切阶段 |
| 导出前 checkpoint，冻结其他 NVS 写入者 | [world.c:283](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/world.c:283) | 导出的应是一个一致版本，不能边生成备份边把不同时间的字段拼起来 |
| 延迟、立即、休眠前保存分级 | [autosave.py:135](/Users/bytedance/luobata/ESP32-PokemonGo/sim/autosave.py:135)、[autosave.py:161](/Users/bytedance/luobata/ESP32-PokemonGo/sim/autosave.py:161) | 借鉴策略结构；触发事件、2 秒防抖等数值由 PokeTactics 定义，不搬捕获/移动事件和 15 分钟阈值 |

两个容易误读的地方：

- PokeWalk 固件**不是** sim 的双槽实现。它采用 NVS 单 blob；
  [save.h:3](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/save.h:3)
  明确解释此选择，也说明固件与 sim 字节布局不同。sim 的
  [DualBufferSave:440](/Users/bytedance/luobata/ESP32-PokemonGo/sim/state.py:440)
  把活动槽标记存在 Python 内存，不能直接当作断电可靠实现。
- `save_decode` 的迁移在内存进行，但当前
  [world.c:1432](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/world.c:1432)
  会在启动迁移后主动保存。PokeTactics 将“只读检查/迁移”与“提交迁移档”
  分开，是本项目的接口选择，不能声称兄弟项目所有读档路径都不回写。

## 3. 最小通用接口

### 3.1 字节存储与结果分类

PC 层建议维持 `SaveStore(backend, codec)` 的组合。异常/结果应足以表达：

| 状态 | PC 表达建议 | 允许动作 |
|---|---|---|
| 真正无档 | `NoSaveError` / EMPTY | 用户选择新游戏后创建 |
| 当前版本有效档 | `LoadedSave` / OK | 返回经过完整验证的候选 |
| 旧版迁移有效档 | `LoadedSave.migrated` / MIGRATED | 返回候选，原字节仍保留；是否持久化由上层提交 |
| 校验或语义损坏 | `CorruptSaveError` / CORRUPT | 保留证据，可从明确有效的旧槽恢复，不能自动伪装空档 |
| 格式/游戏版本不支持 | `UnsupportedVersionError` / UNSUPPORTED | 保留字节，提示升级或使用匹配版本 |
| 读写权限/设备/空间错误 | `StorageIOError` / IO_ERROR | 保留当前状态并允许重试，不建立新档覆盖 |

Backend 的最小能力为 `read(key, max_bytes)` 和
`replace_atomic(key, bytes)`；显式放弃/删除单独提供入口，不能是错误处理的
隐式分支。它不接触 `Session`、物种表、随机数或 UI。

未来 C 接口应采用显式返回值、调用方提供的固定容量 buffer 与长度，避免
把 Python 异常或动态对象作为跨语言合同：

```c
typedef enum {
    STORE_OK, STORE_NOT_FOUND, STORE_TOO_LARGE,
    STORE_IO_ERROR, STORE_COMMIT_UNKNOWN
} store_result_t;

store_result_t store_read(void *ctx, const char *key,
                          uint8_t *out, size_t capacity, size_t *used);
store_result_t store_replace(void *ctx, const char *key,
                             const uint8_t *bytes, size_t size);
```

这些是拟议接口，不代表 C 实现已经存在。schema、校验和及领域错误由上层
SaveStore/Codec 表达；C Backend 的具体错误映射须与 PC fixture 对账。

原子替换承诺“恢复时读到旧完整记录或新完整记录”。不要将任意 I/O 异常
解释为“磁盘必然还是旧档”：例如 rename 成功后目录同步失败，提交结果可能
不确定。这种情况下应重读并核对 revision/digest，未消歧前阻止下一次写入。
PokeWalk 恢复日志对提交标记写入/回读失败也有专门处理：
[restore_journal.c:31](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/restore_journal.c:31)。

### 3.2 信封与 Codec

信封至少区分 `format_version`、`game_id`、`schema_version`、`rules_id`、
`rng_version`、`build_id`、`sequence`、`payload_length`、`digest`。
字段可以属于外层容器或受校验的 payload，但须有一个权威来源。

| 标识 | 兼容意义 |
|---|---|
| format_version | 容器格式，长度/编码/摘要字段如何解释 |
| game_id | 哪个游戏的领域状态；不能将 PokeWalk 数据灌入 PokeTactics |
| schema_version | 字段布局、字段含义及迁移函数的版本 |
| rules_id | 战斗、经济、角色、装备等规则身份；由游戏层决定能否续玩/重放 |
| rng_version | PRNG、采样方法和子流协议身份；影响同状态后续结果 |
| build_id | 来源构建追溯；通常不是 schema 兼容的硬性相等条件 |
| sequence / revision | 同一档案的新旧顺序与提交确认，不能仅靠墙钟排序 |
| digest | 意外损坏检测；CRC/SHA 均不等于备份来源签名 |

通用 Codec 合同为 `encode(state) -> bytes`、
`decode(version, bytes) -> candidate`、`migrate(candidate) -> current`、
`validate(candidate) -> accepted/error`。解码与迁移不写磁盘、不抽 RNG、不发奖。
禁止 pickle 或任意代码执行式解码。

双槽应逐个做长度、摘要、版本和业务校验，选择合法的最新 revision。两个槽
都缺失才是 EMPTY；两个槽都坏是 CORRUPT。一个槽存在更高的不支持版本时，
不能将其视为普通坏槽、回退旧版本后继续覆盖；必须保留并让兼容策略裁决。
读取失败同样不能伪装缺失。

## 4. 自动保存与事务

通用调度器只处理 `mark_dirty(revision, reason)`、`tick(monotonic_now)`、
`flush(reason)`，触发回调提交候选快照。不要照搬
[autosave.py:185](/Users/bytedance/luobata/ESP32-PokemonGo/sim/autosave.py:185)
的成功假设；PC 故障注入后，失败必须保留 dirty 和待保存 revision。

PokeTactics 的保存点：

1. 准备期购买、出售、移动、刷新、装备等操作：标脏；防抖提交。
2. 开战：准备末快照写成功才提交阶段；失败仍可恢复同一准备状态。
3. 回合结算：收入、掉血、奖励、淘汰、下轮初始化需要定义唯一持久化边界，
   重试或恢复不得重复发放。不要在恢复时再次调用已执行过的 `begin_round`。
4. 休眠、低电、主动退出：强制 flush；失败反馈必须与实际持久化状态一致。
5. 终局：局外统计与局内完成标记必须可幂等结算。可以采用 match_id 去重，
   不能“先清局内档，再写生涯档”导致中途断电两边都没有记录。

PC 防抖测试可证明调度逻辑，不证明 ESP32 Flash 寿命或休眠前写入时间。
磨损、空间、峰值 RAM、阻塞时间均需对实际序列化大小和目标硬件单独测量。

## 5. Demo 快照必须保留的领域事实

当前 `docs/09` 是旧概念稿，以下旧假设不能继续作为编码依据：

| 旧条款 | 修订要求 |
|---|---|
| [09:83](/Users/bytedance/luobata/PokeTactics/docs/09-save-system.md:83)：sources/invested 可从物种重推 | 同一终形态可能直购、普通合成或石头进化，成本与占池不同。必须显式保存 `invested` 和 `sources`，再重建并核对共享池 |
| [09:61](/Users/bytedance/luobata/PokeTactics/docs/09-save-system.md:61)：5 商店格/9 备战格 | 当前玩法为 4 格商店/6 格备战；容量和池表身份须绑定 schema/规则，不能沿旧定长示意表 |
| [09:73](/Users/bytedance/luobata/PokeTactics/docs/09-save-system.md:73)：序即阵型 | 玩家棋盘有显式坐标和空洞，必须保存准确格位；Bot 列表顺序也不能丢 |
| [09:187](/Users/bytedance/luobata/PokeTactics/docs/09-save-system.md:187)：两槽坏就判无档 | 两槽坏必须显示损坏并保留原字节，不能自动当新游戏覆盖 |
| [09:204](/Users/bytedance/luobata/PokeTactics/docs/09-save-system.md:204)：reserved 吸收字段即可不升版本 | 字段含义变化也可能不兼容；是否需升版由解码/默认值合同决定，不能用 padding 绕过迁移 |
| 0.55 KB/1.5 KB 槽预算 | 旧示意表遗漏来源、投入、仓库与坐标；先测真实 payload，再定 ESP32 预算，不能继续称为实测大小 |

除棋子身份、投入、来源、装备、坐标外，应保留种子、当前轮、当前阶段、
席位身份/人格/能力、HP/金币/等级/经验/连胜、存活/排名、目标属性、装备与
组件仓库、石头次数、商店顺序、刷新序、上一对手、当前配对和幽灵来源。
配对若已经在准备期生成并展示，恢复时不得重新决定；引用以稳定席位编号
编码，不能存 Python 对象身份。

恢复校验至少覆盖：席位唯一、合法阶段、棋子和道具 ID、非负库存、真实容量、
坐标范围/不重叠、投入与来源有界、共享池不为负且全局守恒、配对引用有效。
语义失败时不得发布部分 Session。资源路径、渲染帧缓存和临时 socket 不入档。

规则变化不等于必然允许续玩。完整快照可以保留既有金币/阵容，但新卡池、
道具删除或成长语义变化仍需迁移；默认由游戏层显式接受或拒绝，保留旧档。
规则不匹配时不能重演出一场不同结果再称为旧回放。

跨语言 RNG 是独立前置条件：当前
[rng.py:17](/Users/bytedance/luobata/PokeTactics/sim/rng.py:17)
只规定派生 seed，并明确 PRNG 本体随端；Python `random.Random` 不会与未来
C 随机实现天然同流。移植前需固定 PRNG、整数/权重采样、消费顺序和 golden
向量；否则只能宣称同一 Python 规则版本内恢复一致，不能宣称 C/Python
同种子同战斗。

## 6. USB 备份与导入：复用协议原则，不搬分区

PokeWalk 的设备协议提供了完整顺序证据：

1. 设备先主动进入导入页，并确认覆盖；
   [usb_backup.c:77](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/usb_backup.c:77)。
2. 确认后先导出当前档，进入 WAIT_ACK；
   [usb_backup.c:111](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/usb_backup.c:111)。
3. 浏览器关闭文件、回读比对之后，才发送匹配会话/请求的 ACK；
   [app.mjs:12](/Users/bytedance/luobata/ESP32-PokemonGo/tools/save-manager/web/app.mjs:12)。
4. 设备收到 ACK 才进入 RECEIVING；分块序号、大小、CRC 全部校验；
   [usb_backup.c:59](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/usb_backup.c:59)。
5. 在隔离暂存 NVS 上读取真实内容，文件声明版本必须与实际版本相符，复用
   启动解码/迁移/领域校验；
   [usb_backup_device.c:46](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/usb_backup_device.c:46)。
6. 新旧镜像均回读校验，最后写提交标记；启动时应用或回滚，无法恢复就禁止
   游戏写入；[restore_journal.c:19](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/restore_journal.c:19)、
   [restore_journal.c:46](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/restore_journal.c:46)。
7. 暂存完成不等于恢复完成；UI 等待重启后的结果确认；
   [app.mjs:47](/Users/bytedance/luobata/ESP32-PokemonGo/tools/save-manager/web/app.mjs:47)。

必须保留的版本区分：备份来源 build 仅追溯，设备按照实际支持的 schema
解码迁移；但已提交恢复日志绑定的是**目标构建**，不能暂存后换固件继续写。
兄弟项目当前宏和解码分支支持 V5–V17，不代表本项目要支持这些业务版本，
也不代表永久支持所有后续版本。

不能直接搬的部分包括 `!PWBACKUP` 游戏命名、MAC/ESP32-C3 限定、NVS 的
`0x9000/0x6000`、暂存区 `0x360000/0x10000`、`pokewalk/state` 键及原始分区
备份；地址检查来自
[usb_backup_device.c:21](/Users/bytedance/luobata/ESP32-PokemonGo/firmware/main/usb_backup_device.c:21)。
通用框架应把游戏身份、设备身份策略、布局和传输限额参数化。跨设备导入须
另设明确模式，不能隐式取消同设备保护。

开发 CLI 也不是网页导入的等价物：
[restore.py:78](/Users/bytedance/luobata/ESP32-PokemonGo/tools/save-manager/restore.py:78)
直写 Flash，保留同设备/同构建保护、预恢复备份和写后回读；它不能调用固件
迁移校验器，也没有网页暂存日志的同等保护。不要删除该限制后声称跨版本
恢复已完成。

本批 PC 的导入前 checkpoint 只能叫“本机旧档保护”。尚无设备确认、电脑
文件回读 ACK、分区日志与重启确认时，不能标记 USB 安全导入已完成。

## 7. 分期交付与验收

| 阶段 | 最小交付 | 放行证据 | 不能据此声称 |
|---|---|---|---|
| P0 · PC 通用参考 | Memory/File Backend，SaveStore，受限信封，版本与错误分类，迁移入口，导入前 checkpoint | 两槽缺失/单槽坏/双槽坏/未来版本/I/O 失败/截断/摘要失败；只读迁移不改字节；写故障后 old-or-new | NVS 可用、Flash 掉电可靠、USB 已接通 |
| P1 · 游戏恢复 | SessionCodec，Demo 保存/继续/导出/导入，保存错误 UI，写点接入 | 同种子同动作下保存恢复与连续游玩：商店、配对、金币、卡池、阵容、战斗结果一致；奖励不重复；坏档不替换当前局 | 旧业务版本已迁移、跨 C/Python 同流、真机操作完成 |
| P2 · C 协议对齐 | 固定字段编码或正式确定的跨端 codec，固定 PRNG/采样，NVS Adapter，构建接线 | Python/C 共用脱敏 golden fixture，序列化字节与 RNG 向量一致；真实 SDK 编译；错误码映射和容量边界 | 只编译成功就等于保档或断电可靠 |
| P3 · 设备持久化 | 初始化、休眠/低电 flush，真实分区预算，性能/内存测量 | 已授权隔离测试设备上：写中断电、重启回退、空间/写失败、升级保档；记录目标板与构建 | 单次启动成功就等于发布兼容 |
| P4 · USB 与发布 | 参数化传输、显式确认、预备份回读 ACK、暂存日志、启动应用/回滚、线上/离线工具同步 | 每个持久化 I/O 点故障注入；真实导出→导入→重启核对；上一公开版本备份迁移；安装路径不擦档 | PC 模拟、兄弟项目历史测试等于本项目真机通过 |

所有 fixture 都应为脱敏合成样本或明确可公开的黄金字节，不从玩家唯一存档
生成测试覆盖。新增 schema 时保留旧 fixture 与默认值断言；允许新增迁移，
不得静默删除已承诺的旧版读取能力。发布记录必须区分“设计完成、PC 测试、
固件编译、真机保档、真机导入”，分别写实际结果及未覆盖项。
