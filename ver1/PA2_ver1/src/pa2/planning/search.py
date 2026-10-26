"""Remaining-set search, independent of CAD and of a removal prefix's order.

Only fully enumerated states are closed. A closed state means no additional
accepted path was found under this run's policy, not physical impossibility.
UNKNOWN outcomes retain that distinction in the path diagnostics.
"""
from __future__ import annotations

import time
from collections import Counter

from .priority import TargetFastenerPriorityProvider, is_fastener


class RemainingSetSearch:
    def __init__(self, groups, contacts, base_id, provider, settings, context,
                 evaluate, cancel_check):
        self.groups = groups
        self.contacts = contacts
        self.base_id = base_id
        self.provider = provider
        self.settings = settings
        self.context = context
        self.evaluate = evaluate
        self.cancel_check = cancel_check
        self.stats = Counter()
        self.closed = set()
        self.visited = set()
        self.evaluations = {}

    def stopped(self):
        if self.cancel_check() or self.context.cancelled:
            self.context.cancelled = True
            return True
        return time.monotonic() >= self.context.deadline

    def run(self, remaining):
        return self.visit(remaining, 0)[0]

    def visit(self, remaining, depth, preferred_target=None):
        context = self.context
        context.max_depth_seen = max(context.max_depth_seen, depth)
        if self.stopped():
            return False, False
        if remaining == {self.base_id}:
            context.best_choices = list(context.choices)
            return True, True
        state = frozenset(remaining)
        self.visited.add(state)
        self.stats["state_visits"] += 1
        if state in self.closed:
            self.stats["closed_state_skips"] += 1
            return False, True

        ranked = self.provider.rank(self.groups, remaining, self.base_id, self.contacts)
        guided = isinstance(self.provider, TargetFastenerPriorityProvider)
        if guided and preferred_target in ranked:
            ranked.remove(preferred_target)
            ranked.insert(0, preferred_target)
            self.stats["preferred_target_retries"] += 1
        attempted = set()

        def candidates():
            for gid in ranked:
                if guided and is_fastener(self.groups[gid]):
                    continue
                yield gid, None
                # The caller evaluates the target before this generator resumes.
                evaluation = self.evaluations.get((state, gid))
                if guided and evaluation is not None and evaluation[0] is None:
                    for fastener in self.provider.related_fasteners(
                            gid, evaluation[1], ranked, self.groups, self.contacts):
                        yield fastener, gid
            if guided:
                # Orphans and fasteners shared by several targets stay eligible.
                for gid in ranked:
                    yield gid, None

        fully_explored = True
        for gid, retry_target in candidates():
            if self.stopped():
                return False, False
            if gid in attempted:
                self.stats["duplicate_group_skips"] += 1
                continue
            attempted.add(gid)
            if retry_target is not None:
                self.stats["related_fastener_attempts"] += 1
            child = remaining - {gid}
            if frozenset(child) in self.closed:
                self.stats["closed_state_skips"] += 1
                continue
            key = (state, gid)
            if key in self.evaluations:
                choice, blockers, finished = self.evaluations[key]
                self.stats["group_evaluation_cache_hits"] += 1
            else:
                choice, blockers, finished = self.evaluate(remaining, gid)
                if finished:
                    self.evaluations[key] = choice, blockers, finished
            if not finished:
                return False, False
            if choice is None:
                continue
            context.choices.append(choice)
            if len(context.choices) > len(context.best_choices):
                context.best_choices = list(context.choices)
            complete, exhausted = self.visit(child, depth + 1, retry_target)
            if complete:
                return True, True
            context.choices.pop()
            fully_explored &= exhausted
            if self.stopped():
                return False, False
            context.backtracks += 1
            # Preserve the existing configured depth limit; do not mistake its
            # early return (or a global budget cutoff) for an exhausted state.
            if depth >= self.settings.backtrack_depth or context.backtracks >= self.settings.backtrack_count:
                return False, False
        if fully_explored:
            self.closed.add(state)
        return False, fully_explored


class ExteriorVirtualSearch(RemainingSetSearch):
    """Probe a target without its contacting fasteners, then prove real removals.

    Virtual choices never enter the retained prefix. All deferred directions and
    orphan fasteners remain in the final fallback enumeration.
    """

    def visit(self, remaining, depth, pending=None):
        context = self.context
        context.max_depth_seen = max(context.max_depth_seen, depth)
        if self.stopped():
            return False, False
        if remaining == {self.base_id}:
            context.best_choices = list(context.choices)
            return True, True
        state = frozenset(remaining)
        self.visited.add(state)
        self.stats['state_visits'] += 1
        if state in self.closed:
            self.stats['closed_state_skips'] += 1
            return False, True
        ranked = self.provider.rank(self.groups, remaining, self.base_id, self.contacts)
        yielded = set()

        def evaluate(ids, gid, phase='quick', preferred=(), virtual=False):
            key = (frozenset(ids), gid, phase, tuple(preferred), virtual)
            if key in self.evaluations:
                self.stats['group_evaluation_cache_hits'] += 1
                return self.evaluations[key]
            result = self.evaluate(ids, gid, phase, preferred, virtual)
            if result[2]:
                self.evaluations[key] = result
            return result

        def candidates():
            if pending and pending[0] in remaining:
                target, fasteners, direction = pending
                todo = [gid for gid in fasteners if gid in remaining]
                for gid in todo:
                    self.stats['related_fastener_attempts'] += 1
                    choice, _, finished = evaluate(remaining, gid, 'all')
                    if choice:
                        yield choice, pending, finished
                    elif not finished:
                        yield None, None, False
                if not todo:
                    self.stats['preferred_target_retries'] += 1
                    choice, _, finished = evaluate(remaining, target, 'all', (direction,))
                    yield choice, None, finished
            for gid in ranked:
                if is_fastener(self.groups[gid]):
                    continue
                choice, blockers, finished = evaluate(remaining, gid)
                if choice or not finished:
                    yield choice, None, finished
                    continue
                related = self.provider.related_fasteners(gid, blockers, ranked, self.groups, self.contacts)
                if related:
                    self.stats['virtual_target_probes'] += 1
                    virtual_remaining = remaining-set(related)
                    probe, _, finished = evaluate(virtual_remaining, gid, 'quick', (), True)
                    if not finished:
                        yield None, None, False
                    if probe:
                        self.stats['virtual_target_passes'] += 1
                        agenda = (gid, tuple(related), tuple(probe.direction))
                        for fastener in related:
                            self.stats['related_fastener_attempts'] += 1
                            actual, _, finished = evaluate(remaining, fastener, 'all')
                            yield actual, agenda, finished
            # Deferred directions and fasteners remain reachable even if a
            # virtual probe is BLOCKED/UNKNOWN, or one member cannot be removed.
            for gid in sorted(ranked, key=lambda gid: not is_fastener(self.groups[gid])):
                choice, _, finished = evaluate(remaining, gid, 'all')
                yield choice, None, finished

        fully_explored = True
        for choice, agenda, finished in candidates():
            if self.stopped() or not finished:
                return False, False
            if choice is None:
                continue
            gid = choice.group_id
            if gid in yielded:
                self.stats['duplicate_group_skips'] += 1
                continue
            yielded.add(gid)
            child = remaining-{gid}
            if frozenset(child) in self.closed:
                self.stats['closed_state_skips'] += 1
                continue
            context.choices.append(choice)
            if len(context.choices) > len(context.best_choices):
                context.best_choices = list(context.choices)
            complete, exhausted = self.visit(child, depth+1, agenda)
            if complete:
                return True, True
            context.choices.pop()
            fully_explored &= exhausted
            if self.stopped():
                return False, False
            context.backtracks += 1
            if depth >= self.settings.backtrack_depth or context.backtracks >= self.settings.backtrack_count:
                return False, False
        if fully_explored:
            self.closed.add(state)
        return False, fully_explored
