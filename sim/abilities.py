"""Fixed species abilities for the explicit tactical-v2 rules.

These are game-specific traits, separate from partner identity and teaching.
Adding a species row does not require a new Battle allowlist or a learning slot.
"""
from copy import deepcopy

from tactics import BASE_RULESET, entry_abilities_enabled
from weather_control import WEATHER_WINDOW_SECONDS


_ABILITIES = {
    38: {"id": "drought", "name": "日照", "weather": "sun"},
    131: {"id": "drizzle", "name": "降雨", "weather": "rain"},
}


def for_species(species_id, ruleset=BASE_RULESET):
    if not entry_abilities_enabled(ruleset):
        return None
    if type(species_id) is not int or species_id not in _ABILITIES:
        return None
    record = deepcopy(_ABILITIES[species_id])
    weather = "晴天" if record["weather"] == "sun" else "雨天"
    record.update(species=species_id, trigger="battle_start", uses=1,
                  duration=WEATHER_WINDOW_SECONDS, custom=True,
                  description=f"本作固定特性：上场时自动制造{WEATHER_WINDOW_SECONDS:g}秒全场{weather}，"
                  "不占教学槽；同刻晴雨相抵，双方共享天气，后续教学可覆盖，每场一次。")
    return record


def catalog(ruleset=BASE_RULESET):
    return [view for species in sorted(_ABILITIES)
            if (view := for_species(species, ruleset)) is not None]
