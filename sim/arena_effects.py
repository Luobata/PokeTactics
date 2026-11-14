"""Arena effect engine: one ordered event bus, declarative effect specs, a ledger.

Every arena rule that reacts to a battle fact subscribes to a named trigger on
``battle.fx``. Legacy hook modules (items, traits, bonds, teaching, offense,
combinations, fields, interactions) are registered first, in exactly the order
combat used to call them inline, so arena_v1 replays stay byte-identical
(guarded by tools/acceptance/arena_golden.py). Depth-edition content
(sim/arena_depth.py) registers declarative ``EffectSpec`` rows after them.

Triggers and their context keywords
-----------------------------------
tick            battle, t                                  (start of each tick)
basic_settled   battle, unit, target, t, action_index, actual_hp
direct_hit      battle, source, target, actual_hp, t, action_index, move, basic
native_primary  battle, unit, target, t, cast_index, lost_hp, move
native_cast     battle, unit, t, cast_index                (after any native cast)
native_heal     battle, unit, patient, actual, t, cast_index
native_energy   battle, unit, recipient, gained, t, cast_index
knockback       battle, source, target, origin, t, cast_index, action_index
debuff          battle, source, target, kind, t
battle_start    battle, t                                  (depth only)
death           battle, unit, killer, t                    (depth only)
"""
from dataclasses import dataclass, field

from data import ENERGY_MAX

EPS = 1e-9


# --------------------------------------------------------------- legacy hooks
def _tick_combinations(battle, t, **_):
    from arena_combinations import expire
    for unit in battle.units:
        expire(battle, unit, t)


def _tick_offense(battle, t, **_):
    from arena_offense import expire
    for unit in battle.units:
        expire(battle, unit, t)


def _tick_fields(battle, t, **_):
    from arena_fields import expire
    expire(battle, t)


def _tick_identities(battle, t, **_):
    from arena_skills import expire
    expire(battle, t)


def _tick_interactions(battle, t, **_):
    from arena_interactions import expire
    expire(battle, t)


def _tick_weather_traits(battle, t, **_):
    from arena_traits import weather_tick
    weather_tick(battle, t)


def _tick_traits(battle, t, **_):
    from arena_traits import expire
    for unit in battle.units:
        expire(battle, unit, t)


def _basic_offense(battle, unit, target, t, action_index, actual_hp, **_):
    from arena_offense import after_basic
    after_basic(battle, unit, target, t, action_index, actual_hp)


def _basic_equipment(battle, unit, target, t, action_index, actual_hp, **_):
    from arena_equipment import after_basic
    after_basic(battle, unit, target, t, action_index, actual_hp)


def _direct_traits(battle, source, target, actual_hp, t, action_index, move, basic, **_):
    from arena_traits import after_direct_hit
    after_direct_hit(battle, source, target, actual_hp, t, action_index, move, basic=basic)


def _direct_bonds(battle, source, target, actual_hp, t, action_index, move, basic, **_):
    from arena_bonds import after_direct_hit
    after_direct_hit(battle, source, target, actual_hp, t, action_index, move, basic=basic)


def _direct_teaching(battle, source, target, actual_hp, t, action_index, **_):
    from arena_teaching import after_hit_taken
    after_hit_taken(battle, target, source, actual_hp, t, action_index)


def _primary_equipment(battle, unit, target, t, cast_index, lost_hp, **_):
    from arena_equipment import after_native_hit
    after_native_hit(battle, unit, target, t, cast_index, lost_hp)


def _primary_bonds(battle, unit, target, t, cast_index, lost_hp, **_):
    from arena_bonds import after_native_hit
    after_native_hit(battle, unit, target, t, cast_index, lost_hp)


def _primary_interactions(battle, unit, target, t, cast_index, lost_hp, move, **_):
    from arena_interactions import after_primary
    after_primary(battle, unit, target, move, lost_hp, t, cast_index)


def _cast_traits(battle, unit, t, cast_index, **_):
    from arena_traits import after_native_cast
    after_native_cast(battle, unit, t, cast_index)


def _cast_bonds(battle, unit, t, cast_index, **_):
    from arena_bonds import after_native_cast
    after_native_cast(battle, unit, t, cast_index)


def _heal_equipment(battle, unit, patient, actual, t, cast_index, **_):
    from arena_equipment import after_native_heal
    after_native_heal(battle, unit, patient, actual, t, cast_index)


def _heal_traits(battle, unit, patient, actual, t, cast_index, **_):
    from arena_traits import after_native_heal
    after_native_heal(battle, unit, patient, actual, t, cast_index)


def _energy_offense(battle, unit, recipient, gained, t, cast_index, **_):
    from arena_offense import after_native_energy
    after_native_energy(battle, unit, recipient, gained, t, cast_index)


def _energy_bonds(battle, unit, recipient, gained, t, cast_index, **_):
    from arena_bonds import after_native_support
    after_native_support(battle, unit, recipient, gained, 'energy', t, cast_index)


def _energy_equipment(battle, unit, recipient, gained, t, cast_index, **_):
    from arena_equipment import after_native_energy
    after_native_energy(battle, unit, recipient, gained, t, cast_index)


def _knock_combinations(battle, source, target, origin, t, cast_index, action_index, **_):
    from arena_combinations import after_knockback
    after_knockback(battle, source, target, origin, t, cast_index, action_index)


def _knock_equipment(battle, source, target, t, cast_index, action_index, **_):
    from arena_equipment import after_knockback
    after_knockback(battle, source, target, t, cast_index, action_index)


def _debuff_equipment(battle, source, target, kind, t, **_):
    from arena_equipment import after_debuff
    after_debuff(battle, source, target, kind, t)


def _debuff_traits(battle, source, target, kind, t, **_):
    from arena_traits import after_debuff
    after_debuff(battle, source, target, kind, t)


def _debuff_teaching(battle, source, target, kind, t, **_):
    from arena_teaching import after_ally_debuff
    after_ally_debuff(battle, source, target, kind, t)


# Order inside each list is the historical inline call order. Do not reorder.
LEGACY_HOOKS = {
    'tick': (_tick_combinations, _tick_offense, _tick_fields, _tick_identities,
             _tick_interactions, _tick_weather_traits, _tick_traits),
    'basic_settled': (_basic_offense, _basic_equipment),
    'direct_hit': (_direct_traits, _direct_bonds, _direct_teaching),
    'native_primary': (_primary_equipment, _primary_bonds, _primary_interactions),
    'native_cast': (_cast_traits, _cast_bonds),
    'native_heal': (_heal_equipment, _heal_traits),
    'native_energy': (_energy_offense, _energy_bonds, _energy_equipment),
    'knockback': (_knock_combinations, _knock_equipment),
    'debuff': (_debuff_equipment, _debuff_traits, _debuff_teaching),
}
TRIGGERS = frozenset(LEGACY_HOOKS) | {'battle_start', 'death'}


class EffectBus:
    """Ordered, synchronous dispatch. Handlers never reorder or skip each other."""

    def __init__(self, battle):
        self.battle = battle
        self.handlers = {trigger: list(hooks) for trigger, hooks in LEGACY_HOOKS.items()}
        self.ledger = Ledger()

    def subscribe(self, trigger, handler):
        if trigger not in TRIGGERS:
            raise ValueError(f'unknown effect trigger {trigger!r}')
        self.handlers.setdefault(trigger, []).append(handler)

    def emit(self, trigger, **context):
        for handler in self.handlers.get(trigger, ()):
            handler(battle=self.battle, **context)


# ------------------------------------------------------------------- ledger
class Ledger:
    """Per-team benefit accounting for every named source (augment, item, ...).

    Values are what actually settled: HP removed, HP restored, shield granted,
    energy gained, plus an ``estimated`` bucket for passive stat bonuses whose
    contribution is derived from settled damage rather than a discrete event.
    """
    FIELDS = ('triggers', 'damage', 'heal', 'shield', 'energy', 'prevented', 'estimated')

    def __init__(self):
        self.rows = ({}, {})

    def add(self, team, source, key, **values):
        row = self.rows[team].setdefault((source, key), dict.fromkeys(self.FIELDS, 0))
        for name, value in values.items():
            row[name] += int(round(value))

    def view(self, team):
        return [{'source': source, 'id': key, **row}
                for (source, key), row in sorted(self.rows[team].items())]


# ------------------------------------------------------- augment stat panels
# Ordered exactly like the original if-chain in Battle._apply_arena_stats.
# atk / hp multiply; dr composes multiplicatively; interval divides; energy adds.
AUGMENT_MODIFIERS = (
    ('sharp_focus', (('atk', 1.12),)),
    ('vitality', (('hp', 1.15),)),
    ('iron_wall', (('dr', .92),)),
    ('quick_step', (('interval', 1.12),)),
    ('mana_flow', (('energy', 20),)),
    ('first_aid', (('heal_mult', 1.3),)),
    ('war_banner', (('atk', 1.06), ('interval', 1.06))),
    ('deep_reserves', (('hp', 1.08), ('energy', 10))),
)


def apply_augment_modifiers(unit, augments, atk_mult, hp_mult):
    """Return updated (atk_mult, hp_mult); mutate dr/interval/energy/heal in place."""
    for key, modifiers in AUGMENT_MODIFIERS:
        if key not in augments:
            continue
        for stat, value in modifiers:
            if stat == 'atk':
                atk_mult *= value
            elif stat == 'hp':
                hp_mult *= value
            elif stat == 'dr':
                unit.arena_dr = 1 - (1 - unit.arena_dr) * value
            elif stat == 'interval':
                unit.attack_interval /= value
            elif stat == 'energy':
                unit.energy = min(ENERGY_MAX, unit.energy + value)
            elif stat == 'heal_mult':
                unit.arena_heal_mult = value
    return atk_mult, hp_mult


# ------------------------------------------------------- declarative effects
@dataclass(frozen=True)
class EffectSpec:
    """One data row. ``handler`` implements the action over a resolved context.

    source   augment | bond | item | core | terrain | skill_mod | edition
    trigger  one of TRIGGERS
    owner    'unit' (instances bound to units) or 'team'
    cooldown seconds between successful activations for one owner
    limit    successful activations per owner per battle (None = unbounded)
    """
    id: str
    source: str
    trigger: str
    name: str
    description: str
    handler: object
    owner: str = 'unit'
    cooldown: float = 0.
    limit: int = None
    params: dict = field(default_factory=dict)
    tags: tuple = ()


class EffectInstance:
    __slots__ = ('spec', 'team', 'unit', 'uses', 'ready_at', 'state')

    def __init__(self, spec, team, unit=None):
        self.spec, self.team, self.unit = spec, team, unit
        self.uses, self.ready_at, self.state = 0, 0., {}

    def ready(self, t):
        if self.unit is not None and not self.unit.alive and self.spec.trigger != 'death':
            return False
        if self.spec.limit is not None and self.uses >= self.spec.limit:
            return False
        return t + EPS >= self.ready_at

    def spend(self, t):
        self.uses += 1
        self.ready_at = t + self.spec.cooldown


def install(battle, instances):
    """Subscribe each instance's handler; activations go through ``fire``."""
    battle.fx_instances = list(instances)
    for instance in battle.fx_instances:
        def dispatch(battle, _instance=instance, **context):
            t = context.get('t', 0.)
            if _instance.ready(t):
                _instance.spec.handler(battle, _instance, **context)
        battle.fx.subscribe(instance.spec.trigger, dispatch)


def fire(battle, instance, target, t, *, label=None, kind='buff', value=0, spend=True,
         camera=None, **payload):
    """Record one successful activation as an 'effect' event and ledger row."""
    source_unit = instance.unit if instance.unit is not None else target
    if spend:
        instance.spend(t)
    battle.events.append((t, 'effect', source_unit.idx if source_unit is not None else -1,
                          target.idx if target is not None else -1, instance.spec.id,
                          {'source': instance.spec.source, 'team': instance.team, 'kind': kind,
                           'label': label or instance.spec.name, 'value': int(value),
                           **({'camera': camera} if camera else {}), **payload}))
    ledger_value = {'damage': 'damage', 'heal': 'heal', 'shield': 'shield',
                    'energy': 'energy', 'prevented': 'prevented'}.get(kind)
    battle.fx.ledger.add(instance.team, instance.spec.source, instance.spec.id,
                         triggers=1, **({ledger_value: value} if ledger_value else {}))
