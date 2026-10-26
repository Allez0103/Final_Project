"""Resolve shared bolt/nut attachments before excluding them from CAD search."""
from .priority import is_fastener


def fastener_attachments(groups, contacts, base_id):
    fasteners = {gid for gid, group in groups.items() if gid != base_id and is_fastener(group)}
    graph = {gid: set() for gid in groups}
    for edge in contacts:
        if edge.group_a in graph and edge.group_b in graph:
            graph[edge.group_a].add(edge.group_b)
            graph[edge.group_b].add(edge.group_a)
    result = {}
    for gid in sorted(fasteners):
        seen, pending, targets = set(), [gid], set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            for neighbor in graph[current]:
                if neighbor in fasteners:
                    pending.append(neighbor)
                else:
                    targets.add(neighbor)
        moving = sorted(targets-{base_id})
        result[gid] = {'targets': moving, 'fixed_target': base_id in targets,
                       'method': 'contact_and_fastener_chain' if targets else 'orphan_fixed_base'}
    return result
