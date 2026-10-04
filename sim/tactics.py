"""Explicit, versioned opt-in for bounded tactical expedition mechanics.

Stat allocation and battle rules are independent: ``budget_v1`` is a stat mode,
whereas ``tactics_v1`` opts a new match into guard and weather teaching.
"""

BASE_RULESET = "base_v1"
TACTICS_RULESET = "tactics_v1"


def validate_ruleset(value):
    if not isinstance(value, str) or value not in (BASE_RULESET, TACTICS_RULESET):
        raise ValueError("unknown battle ruleset")
    return value


def enabled(value):
    return validate_ruleset(value) == TACTICS_RULESET


def validate_team(value, count, ruleset=BASE_RULESET):
    """Validate local-index selections without choosing a replacement source.

    Learning and deployed geometry require battle units and are checked by
    Battle after deployment. Return fresh dictionaries, never the caller's data.
    """
    active = enabled(ruleset)
    if value is None:
        return {"guard": None, "weather": None}
    if not isinstance(value, dict) or set(value) - {"guard", "weather"}:
        raise ValueError("tactics must contain only guard and weather selections")
    result = {"guard": None, "weather": None}
    for kind, fields in (("guard", {"source", "target"}), ("weather", {"source"})):
        selection = value.get(kind)
        if selection is None:
            continue
        if not active:
            raise ValueError("tactical selections require tactics_v1")
        if not isinstance(selection, dict) or set(selection) != fields:
            raise ValueError("invalid " + kind + " selection")
        if any(type(index) is not int or not 0 <= index < count
               for index in selection.values()):
            raise ValueError("tactical selections must reference deployed local indices")
        if kind == "guard" and selection["source"] == selection["target"]:
            raise ValueError("a guard must protect another unit")
        result[kind] = dict(selection)
    return result
