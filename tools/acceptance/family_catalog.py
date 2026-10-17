"""Read-only arena family reference, calculated from the actual combat panel."""
from collections import Counter
from functools import lru_cache
import arena_families as families
from data import pokedex

@lru_cache(maxsize=2)
def catalog_view(version=families.VERSION):
    import demo
    import arena_bonds
    dex = pokedex()
    rows = []
    for fid, (cost, paths) in families.families_for(version).items():
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
                         generation=dex.generation_of(fid), branches=branches))
    return dict(ok=True, version=version, families=rows,
                bond_catalog=[dict(id=row['id'], name=row['name']) for row in arena_bonds.catalog()],
                distribution=dict(Counter(row['cost'] for row in rows)),
                forms=len(families.pool_caps(version)), total_stock=sum(row['stock'] for row in rows),
                note='面板来自实战计算，包含费用预算、培养与定位；不含装备、羁绊、海克斯及战中特性触发。面板不能代表胜率。')


@lru_cache(maxsize=2)
def reference_view(version=families.VERSION):
    dex = pokedex()
    selected = families.families_for(version)
    active = families.pool_caps(version)
    rows = []
    for sid, record in sorted(dex.reference_species.items()):
        fid = families.SPECIES_FAMILY.get(sid) if sid in active else None
        rows.append(dict(id=sid, name=record['name_zh'], name_en=record['name'],
                         generation=dex.generation_of(sid), types=record['types'],
                         base=record['base'], lineage=record['lineage'],
                         evolves_to=record.get('evolves_to', []),
                         playable=fid is not None, family=fid,
                         family_name=dex.species_record(fid)['name_zh'] if fid else None,
                         cost=selected[fid][0] if fid else None))
    return dict(ok=True, version=version, species=rows,
                note='这里展示第三世代原作资料，种族值不是竞技部署面板。只有标记为已入竞技的精选家族能在当前卡池培养；资料收录不会自动增加商店候选。')
