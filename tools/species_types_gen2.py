"""关都 151 只宝可梦的金银世代（Gen2）属性组合表。

PokeWalk 的提取链里没有以结构化形式保存每只宝可梦的属性组合
（种族值、招式、克制表、进化链都有），因此这里手工整理一份。

要点：
- 采用金银世代判定：三合一磁怪（Magnemite/Magneton）为 ELECTRIC/STEEL，
  这是 Gen1→Gen2 唯一的既有宝可梦属性变更；
- 其余与初代一致；不含 Gen6 起的 FAIRY 改动（皮皮、胖丁仍为 NORMAL）；
- 顺序与种族值表一致（全国图鉴 001-151）。

校验方式：可与 PokeAPI `https://pokeapi.co/api/v2/pokemon/{id}` 的
`types`（取 generation ii 版本）逐条比对。
"""

# 全国图鉴 ID -> 属性组合（单属性用单元素元组）
SPECIES_TYPES_GEN2 = {
    1: ("GRASS", "POISON"),      # 妙蛙种子 Bulbasaur
    2: ("GRASS", "POISON"),      # 妙蛙草 Ivysaur
    3: ("GRASS", "POISON"),      # 妙蛙花 Venusaur
    4: ("FIRE",),                # 小火龙 Charmander
    5: ("FIRE",),                # 火恐龙 Charmeleon
    6: ("FIRE", "FLYING"),       # 喷火龙 Charizard
    7: ("WATER",),               # 杰尼龟 Squirtle
    8: ("WATER",),               # 卡咪龟 Wartortle
    9: ("WATER",),               # 水箭龟 Blastoise 御三家完成
    10: ("BUG",),                # 绿毛虫 Caterpie
    11: ("BUG",),                # 铁甲蛹 Metapod
    12: ("BUG", "FLYING"),       # 巴大蝶 Butterfree
    13: ("BUG", "POISON"),       # 独角虫 Weedle
    14: ("BUG", "POISON"),       # 铁壳蛹 Kakuna
    15: ("BUG", "POISON"),       # 大针蜂 Beedrill
    16: ("NORMAL", "FLYING"),    # 波波 Pidgey
    17: ("NORMAL", "FLYING"),    # 比比鸟 Pidgeotto
    18: ("NORMAL", "FLYING"),    # 大比鸟 Pidgeot
    19: ("NORMAL",),             # 小拉达 Rattata
    20: ("NORMAL",),             # 拉达 Raticate
    21: ("NORMAL", "FLYING"),    # 烈雀 Spearow
    22: ("NORMAL", "FLYING"),    # 大嘴雀 Fearow
    23: ("POISON",),             # 阿柏蛇 Ekans
    24: ("POISON",),             # 阿柏怪 Arbok
    25: ("ELECTRIC",),           # 皮卡丘 Pikachu
    26: ("ELECTRIC",),           # 雷丘 Raichu
    27: ("GROUND",),             # 穿山鼠 Sandshrew
    28: ("GROUND",),             # 穿山王 Sandslash
    29: ("POISON",),             # 尼多兰 Nidoran♀
    30: ("POISON",),             # 尼多娜 Nidorina
    31: ("POISON", "GROUND"),    # 尼多后 Nidoqueen
    32: ("POISON",),             # 尼多朗 Nidoran♂
    33: ("POISON",),             # 尼多力诺 Nidorino
    34: ("POISON", "GROUND"),    # 尼多王 Nidoking
    35: ("NORMAL",),             # 皮皮 Clefairy
    36: ("NORMAL",),             # 皮可西 Clefable
    37: ("FIRE",),               # 六尾 Vulpix
    38: ("FIRE",),               # 九尾 Ninetales
    39: ("NORMAL",),             # 胖丁 Jigglypuff
    40: ("NORMAL",),             # 胖可丁 Wigglytuff
    41: ("POISON", "FLYING"),    # 超音蝠 Zubat
    42: ("POISON", "FLYING"),    # 大嘴蝠 Golbat
    43: ("GRASS", "POISON"),     # 走球 Oddish
    44: ("GRASS", "POISON"),     # 臭臭花 Gloom
    45: ("GRASS", "POISON"),     # 霸王花 Vileplume
    46: ("BUG", "GRASS"),        # 派拉斯 Paras
    47: ("BUG", "GRASS"),        # 派拉斯特 Parasect
    48: ("BUG", "POISON"),       # 毛球 Venonat
    49: ("BUG", "POISON"),       # 摩鲁蛾 Venomoth
    50: ("GROUND",),             # 地鼠 Diglett
    51: ("GROUND",),             # 三地鼠 Dugtrio
    52: ("NORMAL",),             # 喵喵 Meowth
    53: ("NORMAL",),             # 猫老大 Persian
    54: ("WATER",),              # 可达鸭 Psyduck
    55: ("WATER",),              # 哥达鸭 Golduck
    56: ("FIGHTING",),           # 猴怪 Mankey
    57: ("FIGHTING",),           # 火爆猴 Primeape
    58: ("FIRE",),               # 卡蒂狗 Growlithe
    59: ("FIRE",),               # 风速狗 Arcanine
    60: ("WATER",),              # 蚊香蝌蚪 Poliwag
    61: ("WATER",),              # 蚊香君 Poliwhirl
    62: ("WATER", "FIGHTING"),   # 蚊香泳士 Poliwrath
    63: ("PSYCHIC",),            # 凯西 Abra
    64: ("PSYCHIC",),            # 勇基拉 Kadabra
    65: ("PSYCHIC",),            # 胡地 Alakazam
    66: ("FIGHTING",),           # 腕力 Machop
    67: ("FIGHTING",),           # 豪力 Machoke
    68: ("FIGHTING",),           # 怪力 Machamp
    69: ("GRASS", "POISON"),     # 喇叭芽 Bellsprout
    70: ("GRASS", "POISON"),     # 口呆花 Weepinbell
    71: ("GRASS", "POISON"),     # 大食花 Victreebel
    72: ("WATER", "POISON"),     # 玛瑙水母 Tentacool
    73: ("WATER", "POISON"),     # 毒刺水母 Tentacruel
    74: ("ROCK", "GROUND"),      # 小拳石 Geodude
    75: ("ROCK", "GROUND"),      # 隆隆石 Graveler
    76: ("ROCK", "GROUND"),      # 阆隆岩 Golem
    77: ("FIRE",),               # 小炭仔 Ponyta
    78: ("FIRE",),               # 烈焰马 Rapidash
    79: ("WATER", "PSYCHIC"),    # 呆呆兽 Slowpoke
    80: ("WATER", "PSYCHIC"),    # 呆呆王 Slowbro
    81: ("ELECTRIC", "STEEL"),   # 三合一磁怪 Magnemite（Gen2 增加 STEEL）
    82: ("ELECTRIC", "STEEL"),   # 磁怪 Magneton（Gen2 增加 STEEL）
    83: ("NORMAL", "FLYING"),    # 大葱鸭 Farfetch'd
    84: ("NORMAL", "FLYING"),    # 嘟嘟 Doduo
    85: ("NORMAL", "FLYING"),    # 嘟嘟利 Dodrio
    86: ("WATER",),              # 小海狮 Seel
    87: ("WATER", "ICE"),        # 白海狮 Dewgong
    88: ("POISON",),             # 臭泥 Grimer
    89: ("POISON",),             # 臭臭泥 Muk
    90: ("WATER",),              # 大舌贝 Shellder
    91: ("WATER", "ICE"),        # 刺甲贝 Cloyster
    92: ("GHOST", "POISON"),     # 鬼斯 Gastly
    93: ("GHOST", "POISON"),     # 鬼斯通 Haunter
    94: ("GHOST", "POISON"),     # 耿鬼 Gengar
    95: ("ROCK", "GROUND"),      # 大岩蛇 Onix
    96: ("PSYCHIC",),            # 催眠貘 Drowzee
    97: ("PSYCHIC",),            # 引梦貘人 Hypno
    98: ("WATER",),              # 大钳蟹 Krabby
    99: ("WATER",),              # 巨钳蟹 Kingler
    100: ("ELECTRIC",),          # 霹雳电球 Voltorb
    101: ("ELECTRIC",),          # 顽皮雷弹 Electrode
    102: ("GRASS", "PSYCHIC"),   # 蛋蛋 Exeggcute
    103: ("GRASS", "PSYCHIC"),   # 椰蛋树 Exeggutor
    104: ("GROUND",),            # 卡拉卡拉 Cubone
    105: ("GROUND",),            # 嘎啦嘎啦 Marowak
    106: ("FIGHTING",),          # 飞腿郎 Hitmonlee
    107: ("FIGHTING",),          # 快拳郎 Hitmonchan
    108: ("NORMAL",),            # 大舌头 Lickitung
    109: ("POISON",),            # 瓦斯弹 Koffing
    110: ("POISON",),            # 双弹瓦斯 Weezing
    111: ("GROUND", "ROCK"),     # 独角犀牛 Rhyhorn
    112: ("GROUND", "ROCK"),     # 钻角犀兽 Rhydon
    113: ("NORMAL",),            # 吉利蛋 Chansey
    114: ("GRASS",),             # 蔓藤怪 Tangela
    115: ("NORMAL",),            # 袋兽 Kangaskhan
    116: ("WATER",),             # 墨海马 Horsea
    117: ("WATER",),             # 海刺龙 Seadra
    118: ("WATER",),             # 角金鱼 Goldeen
    119: ("WATER",),             # 金鱼王 Seaking
    120: ("WATER",),             # 海星星 Staryu
    121: ("WATER", "PSYCHIC"),   # 宝石海星 Starmie
    122: ("PSYCHIC",),           # 魔墙人偶 Mr. Mime
    123: ("BUG", "FLYING"),      # 飞天螳螂 Scyther
    124: ("ICE", "PSYCHIC"),     # 迷唇姐 Jynx
    125: ("ELECTRIC",),          # 电击兽 Electabuzz
    126: ("FIRE",),              # 鸭嘴火兽 Magmar
    127: ("BUG",),               # 凯罗斯 Pinsir
    128: ("NORMAL",),            # 肯泰罗 Tauros
    129: ("WATER",),             # 鲤鱼王 Magikarp
    130: ("WATER", "FLYING"),    # 暴鲤龙 Gyarados
    131: ("WATER", "ICE"),       # 拉普拉斯 Lapras
    132: ("NORMAL",),            # 百变怪 Ditto
    133: ("NORMAL",),            # 伊布 Eevee
    134: ("WATER",),             # 水伊布 Vaporeon
    135: ("ELECTRIC",),          # 雷伊布 Jolteon
    136: ("FIRE",),              # 火伊布 Flareon
    137: ("NORMAL",),            # 多边兽 Porygon
    138: ("ROCK", "WATER"),      # 菊石兽 Omanyte
    139: ("ROCK", "WATER"),      # 多刺菊石兽 Omastar
    140: ("ROCK", "WATER"),      # 化石盔 Kabuto
    141: ("ROCK", "WATER"),      # 镰刀盔 Kabutops
    142: ("ROCK", "FLYING"),     # 化石翼龙 Aerodactyl
    143: ("NORMAL",),            # 卡比兽 Snorlax
    144: ("ICE", "FLYING"),      # 急冻鸟 Articuno
    145: ("ELECTRIC", "FLYING"), # 闪电鸟 Zapdos
    146: ("FIRE", "FLYING"),     # 火焰鸟 Moltres
    147: ("DRAGON",),            # 迷你龙 Dratini
    148: ("DRAGON",),            # 哈克龙 Dragonair
    149: ("DRAGON", "FLYING"),   # 快龙 Dragonite
    150: ("PSYCHIC",),           # 超梦 Mewtwo
    151: ("PSYCHIC",),           # 梦幻 Mew
}

assert len(SPECIES_TYPES_GEN2) == 151
assert set(SPECIES_TYPES_GEN2) == set(range(1, 152))
