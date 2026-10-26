"""Preference similarity, never a physical validation score."""
from math import acos, degrees


def _lcs(a, b):
    row = [0]*(len(b)+1)
    for x in a:
        previous = 0
        for j, y in enumerate(b, 1):
            old = row[j]
            row[j] = previous+1 if x == y else max(row[j], row[j-1])
            previous = old
    return row[-1]


def compare_orders(original, confirmed, groups, exception_ids=()):
    from pa2.planning.priority import is_fastener
    mapping = {g.id: g for g in groups}
    general = {gid for gid, g in mapping.items() if not is_fastener(g)}
    results = {}
    old = {s.group_id: s for s in original.steps}
    new = {s.group_id: s for s in confirmed.steps}
    common = set(old) & set(new)
    for label, allowed in [('all', common), ('general', common & general),
                           ('general_without_exceptions', common & general-set(exception_ids))]:
        a = [s.group_id for s in original.steps if s.group_id in allowed]
        b = [s.group_id for s in confirmed.steps if s.group_id in allowed]
        ranks = {gid: i for i, gid in enumerate(b)}
        pairs = len(a)*(len(a)-1)//2
        preserved = sum(ranks[a[i]] < ranks[a[j]] for i in range(len(a)) for j in range(i+1, len(a)))
        same = sum(degrees(acos(max(-1., min(1., sum(x*y for x, y in zip(
            old[gid].removal_direction, new[gid].removal_direction)))))) <= 1. for gid in a)
        lcs = _lcs(a, b)
        results[label] = dict(count=len(a), pair_count=pairs, preserved_pairs=preserved,
            pair_order_ratio=preserved/pairs if pairs else None,
            lcs_length=lcs, lcs_ratio=lcs/len(a) if a else None,
            direction_same=same, direction_changed=len(a)-same,
            direction_agreement=same/len(a) if a else None)
    results.update(added_ids=sorted(set(new)-set(old)), removed_ids=sorted(set(old)-set(new)),
        preference_only=True, direction_tolerance_deg=1.)
    return results
