"""One bond catalog contract for the dex and saved-battle presentation."""
import arena_bonds


def catalog_for_templates(templates):
    """Include legal current forms and the identity used to count each member."""
    result = []
    for row in arena_bonds.catalog():
        members = sorted(sid for sid in templates
                         if row['id'] in arena_bonds.memberships(sid))
        if not members:
            continue
        identity_by_species = {str(sid): templates[sid].family_id for sid in members}
        result.append({**row, 'members': members, 'pool_size': len(members),
                       'count_unit': '家族',
                       'identity_count': len(set(identity_by_species.values())),
                       'identity_by_species': identity_by_species,
                       'description': row['description'].replace('不同种族', '不同家族')})
    return result
