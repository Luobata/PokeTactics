"""Per-run tactical research ledgers driven by settled trait contributions.

The battle layer only exposes evidence; the session layer owns the durable
ledger.  A route advances at most once per seat/round/track and at most five
times per run, so playback, loading, and ghost mirrors cannot duplicate rewards.
"""
import copy

TRACKS = ('sustain', 'assault', 'tempo')
STACK_LIMIT = 5
HP_STEP = .01
ATTACK_STEP = .01
ENERGY_STEP = 1

SPECS = {
    'sustain': {
        'name': '生存研习', 'species': (134,), 'effects': ('heal',),
        'condition': '水伊布的特性在本场战斗产生有效治疗',
        'reward': '每层全队最大生命 +1%', 'limit': STACK_LIMIT,
    },
    'assault': {
        'name': '强攻研习', 'species': (136, 196), 'effects': ('empowered_hit',),
        'condition': '火伊布或太阳伊布的特性造成结算后的额外实际伤害',
        'reward': '每层全队攻击与特攻 +1%', 'limit': STACK_LIMIT,
    },
    'tempo': {
        'name': '节奏研习', 'species': (135, 197, 198), 'effects': ('energy', 'energy_drain', 'absorb'),
        'condition': '雷伊布、月亮伊布或黑暗鸦的特性产生有效回能或护盾实际吸收',
        'reward': '每层全队开战能量 +1', 'limit': STACK_LIMIT,
    },
}


def catalog():
    """Stable presentation contract; UI must not infer rules from species alone."""
    return [
        {'id': track, 'name': spec['name'], 'condition': spec['condition'],
         'reward': spec['reward'], 'limit': spec['limit'], 'species': list(spec['species'])}
        for track, spec in SPECS.items()
    ]


def view(state, seat_no=0):
    """Player-facing progress view derived only from the durable ledger."""
    state = normalize_state(state)
    if type(seat_no) is not int or not 0 <= seat_no < 8:
        raise ValueError('战术研习席位无效')
    ledger = state['seats'][seat_no]
    tracks = [{**copy.deepcopy(SPECS[track]), 'id': track,
               'stacks': ledger['stacks'][track]} for track in TRACKS]
    return {
        'version': 1, 'tracks': tracks,
        'last_round': max((row['round'] for row in ledger['settlements']), default=0),
        'earned': [row['track'] for row in ledger['settlements']
                   if row['round'] == max((item['round'] for item in ledger['settlements']), default=0)],
        'description': '本局战术研习：指定分支特性产生真实战斗贡献后推进；每轮每路线最多1层，各最多5层，收益下一场生效。',
    }


def empty_stacks():
    return {track: 0 for track in TRACKS}


def initial_state():
    return {'version': 1, 'seats': [
        {'stacks': empty_stacks(), 'settlements': []} for _ in range(8)
    ]}


def normalize_state(value):
    """Return a private normalized state or raise ValueError for forged data."""
    if (not isinstance(value, dict) or type(value.get('version')) is not int
            or value.get('version') != 1):
        raise ValueError('战术研习版本无效')
    seats = value.get('seats')
    if not isinstance(seats, list) or len(seats) != 8:
        raise ValueError('战术研习席位无效')
    normalized = {'version': 1, 'seats': []}
    for seat_no, row in enumerate(seats):
        if not isinstance(row, dict):
            raise ValueError('战术研习账本无效')
        stacks = row.get('stacks')
        if not isinstance(stacks, dict) or set(stacks) != set(TRACKS):
            raise ValueError('战术研习层数无效')
        if any(type(stacks[track]) is not int or not 0 <= stacks[track] <= STACK_LIMIT
               for track in TRACKS):
            raise ValueError('战术研习层数超出范围')
        raw = row.get('settlements')
        if not isinstance(raw, list):
            raise ValueError('战术研习结算记录无效')
        settlements = []
        seen = set()
        previous_round = 0
        for record in raw:
            if not isinstance(record, dict):
                raise ValueError('战术研习结算记录无效')
            round_no = record.get('round')
            track = record.get('track')
            seat = record.get('seat')
            sources = record.get('sources')
            evidence = record.get('evidence_count')
            if (type(round_no) is not int or not 1 <= round_no <= 100 or track not in SPECS
                    or type(seat) is not int or seat != seat_no
                    or not isinstance(sources, list) or not sources
                    or any(source not in SPECS[track]['species'] for source in sources)
                    or len(sources) != len(set(sources))
                    or type(evidence) is not int or not 1 <= evidence <= 100
                    or record.get('amount') != 1
                    or record.get('id') != f'seat{seat}:r{round_no}:{track}'):
                raise ValueError('战术研习结算记录无效')
            key = (round_no, track)
            if key in seen or round_no < previous_round:
                raise ValueError('战术研习结算顺序或唯一性无效')
            seen.add(key)
            previous_round = round_no
            settlements.append({
                'id': record['id'], 'round': round_no, 'seat': seat, 'track': track,
                'sources': sorted(sources), 'evidence_count': evidence, 'amount': 1,
            })
        for track in TRACKS:
            count = sum(row['track'] == track for row in settlements)
            if count != stacks[track]:
                raise ValueError('战术研习层数与结算记录不一致')
        normalized['seats'].append({'stacks': dict(stacks), 'settlements': settlements})
    return normalized


def stacks_for(state, seat_no, before_round=None):
    """Stacks available to a battle; same-round settlements start next battle."""
    ledger = normalize_state(state)['seats'][seat_no]
    if before_round is None:
        return dict(ledger['stacks'])
    if type(before_round) is not int or not 0 <= before_round <= 100:
        raise ValueError('战术研习轮数无效')
    return {track: sum(row['round'] < before_round and row['track'] == track
                       for row in ledger['settlements'])
            for track in TRACKS}


def review(battle, team):
    """Read one committed battle and return routes proven by real trait packets."""
    if not getattr(battle, '_arena_on', False):
        raise ValueError('战术研习只能读取竞技战斗')
    if type(team) is not int or team not in (0, 1):
        raise ValueError('战术研习阵营无效')
    from arena_traits import for_species
    evidence = {track: {'species': set(), 'count': 0} for track in TRACKS}
    for event in battle.events:
        if event[1] != 'combo_effect':
            continue
        _, _, source_idx, target_idx, key, effect, payload = event
        if effect not in ('heal', 'empowered_hit', 'energy', 'energy_drain', 'absorb'):
            continue
        if not isinstance(payload, dict) or type(source_idx) is not int or type(target_idx) is not int:
            continue
        if not 0 <= source_idx < len(battle.units) or not 0 <= target_idx < len(battle.units):
            continue
        source, target = battle.units[source_idx], battle.units[target_idx]
        if source.team != team or source.team != target.team and effect not in ('empowered_hit', 'energy_drain'):
            continue
        sid = source.piece.species_id
        spec = for_species(sid, getattr(source.piece, 'arena_trait_key', None))
        if spec is None or spec.get('id') != key:
            continue
        amount = payload.get('amount')
        if effect == 'empowered_hit':
            amount = payload.get('extra_damage', amount)
        elif effect == 'energy_drain':
            amount = payload.get('gained', 0)
        if type(amount) is not int or amount <= 0:
            continue
        candidates = [track for track in TRACKS
                      if sid in SPECS[track]['species'] and effect in SPECS[track]['effects']]
        if len(candidates) != 1:
            continue
        row = evidence[candidates[0]]
        row['species'].add(sid)
        row['count'] += 1
    return {
        track: {'species': sorted(row['species']), 'evidence_count': row['count']}
        for track, row in evidence.items()
        if row['count']
    }


def settle(state, seat_no, round_no, evidence):
    """Commit in place at most one point per seat/round/track."""
    # Validate the whole durable object first, then mutate the caller's ledger;
    # a copied return value would silently discard the newly earned stacks.
    normalize_state(state)
    if type(seat_no) is not int or not 0 <= seat_no < 8:
        raise ValueError('战术研习席位无效')
    if type(round_no) is not int or not 1 <= round_no <= 100:
        raise ValueError('战术研习轮数无效')
    if not isinstance(evidence, dict):
        raise ValueError('战术研习证据无效')
    ledger = state['seats'][seat_no]
    earned = []
    for track in TRACKS:
        row = evidence.get(track)
        if row is None:
            continue
        if not isinstance(row, dict):
            raise ValueError('战术研习证据无效')
        count = row.get('evidence_count')
        if type(count) is not int or count < 1:
            raise ValueError('战术研习证据无效')
        # Routes still advance only once per round; high-frequency real battles
        # record a bounded count instead of failing settlement above 100 hits.
        count = min(count, 100)
        species = row.get('species')
        if (not isinstance(species, list) or not species
                or any(sid not in SPECS[track]['species'] for sid in species)
                or species != sorted(set(species))):
            raise ValueError('战术研习证据来源无效')
        key = (round_no, track)
        if ledger['stacks'][track] >= STACK_LIMIT or any(
                settled['round'] == round_no and settled['track'] == track
                for settled in ledger['settlements']):
            continue
        ledger['settlements'].append({
            'id': f'seat{seat_no}:r{round_no}:{track}', 'round': round_no,
            'seat': seat_no, 'track': track, 'sources': species,
            'evidence_count': count, 'amount': 1,
        })
        ledger['stacks'][track] += 1
        earned.append(track)
    ledger['settlements'].sort(key=lambda row: (row['round'], TRACKS.index(row['track'])))
    return earned


def settled_round_limit(round_no, phase):
    return round_no - (phase == 'prep')


def validate_history(state, round_no, phase):
    """Cross-check durable records against the run clock after decode."""
    state = normalize_state(state)
    limit = settled_round_limit(round_no, phase)
    for ledger in state['seats']:
        for row in ledger['settlements']:
            if row['round'] > limit:
                raise ValueError('战术研习包含未结算轮次')
    return state
