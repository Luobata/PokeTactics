"""Read-only arena family reference, calculated from the actual combat panel."""
from collections import Counter
from functools import lru_cache
import arena_families as families
from data import pokedex

@lru_cache(maxsize=1)
def catalog_view():
    import demo
    dex = pokedex()
    rows = []
    for fid, (cost, paths) in families.FAMILIES.items():
        branches = []
        for path in paths:
            stages = []
            for step in range(1, 2 if fid in families.RARE else 4):
                piece = families.make_piece(fid, step, path[-1])
                view = demo._piece_view(piece, ruleset='arena_v1')
                view.update(copies=3 ** (step - 1), total_cost=cost * 3 ** (step - 1),
                            growth_label=('稀有 · 限一' if fid in families.RARE else
                                          ('初始', '进阶', '满培养')[step - 1]))
                stages.append(view)
            branches.append(dict(id=path[-1], name=dex.species_record(path[-1])['name_zh'],
                                 path=list(path), stages=stages))
        rows.append(dict(id=fid, name=dex.species_record(fid)['name_zh'], cost=cost,
                         stock=families.POOL_BY_COST[cost], rare=fid in families.RARE,
                         generation=1 if fid <= 151 else 2, branches=branches))
    return dict(ok=True, version=families.VERSION, families=rows,
                distribution=dict(Counter(row['cost'] for row in rows)),
                forms=len(families.SPECIES_FAMILY), total_stock=sum(row['stock'] for row in rows),
                note='面板来自实战计算，包含费用预算、培养与定位；不含装备、羁绊、海克斯及战中特性触发。面板不能代表胜率。')
