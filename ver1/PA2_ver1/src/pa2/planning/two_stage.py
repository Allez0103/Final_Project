"""Exterior general-part draft, with fasteners inserted as atomic bundles."""
import time

from .priority import ExteriorPriorityProvider, is_fastener
from .search import RemainingSetSearch


class TwoStagePriorityProvider(ExteriorPriorityProvider):
    name = 'general-first-fastener-insertion-v16'

    def __init__(self):
        super().__init__(name=self.name)
        self.skeleton = []

    def rank(self, groups, remaining, base_group_id, contacts):
        ranked = super().rank(groups, remaining, base_group_id, contacts)
        ranked += sorted(remaining - {base_group_id} - set(ranked))
        positions = {gid: i for i, gid in enumerate(self.skeleton)}
        return sorted(ranked, key=lambda gid: (
            is_fastener(groups[gid]), positions.get(gid, len(positions))))


class TwoStageSearch(RemainingSetSearch):
    def run(self, remaining):
        ids = {gid for gid in remaining if gid == self.base_id or not is_fastener(self.groups[gid])}
        self.context.skeleton_total = len(ids)-1
        self.skeleton = []
        started = time.perf_counter()
        self.skeleton_budget_fraction = 1.0
        # The single CAD search contains only general parts. Its retained
        # choices are used directly; fasteners are inserted after completion.
        complete = RemainingSetSearch.visit(self, ids, 0)[0]
        self.skeleton = [c.group_id for c in self.context.best_choices
                         if c.group_id in ids and c.group_id != self.base_id]
        self.context.skeleton_steps = len(self.skeleton)
        self.skeleton_budget_exhausted = time.monotonic() >= self.context.deadline and not complete
        self.skeleton_remaining = self.provider.rank(self.groups, ids-set(self.skeleton), self.base_id, self.contacts)
        self.skeleton_elapsed_sec = time.perf_counter()-started
        self.provider.skeleton = self.skeleton + self.skeleton_remaining
        return complete

    def visit(self, remaining, depth, pending=None):
        context = self.context
        context.max_depth_seen = max(context.max_depth_seen, depth)
        if self.stopped():return False, False
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

        def evaluate(ids, gid):
            key = (frozenset(ids), gid)
            if key in self.evaluations:
                self.stats['group_evaluation_cache_hits'] += 1
                return self.evaluations[key]
            result = self.evaluate(ids, gid, 'all')
            if result[2]:self.evaluations[key] = result
            return result

        def candidates():
            generals = [gid for gid in ranked if not is_fastener(self.groups[gid])]
            if not generals:
                bundle = []
                ids = set(remaining)
                for gid in ranked:
                    bundle.append(self.assign_fastener(ids, gid, self.base_id))
                    ids.remove(gid)
                yield bundle, True
                return
            for gid in generals:
                choice, blockers, finished = evaluate(remaining, gid)
                if not finished:
                    yield [], False
                    return
                if choice:
                    yield [choice], True
                    continue
                related = set(self.provider.related_fasteners(gid, blockers, ranked, self.groups, self.contacts))
                # Include fasteners revealed by the target path even when the
                # initial contact graph missed them.
                while related and not self.stopped():
                    trial = remaining-related
                    self.stats['virtual_target_probes'] += 1
                    choice, blockers, finished = evaluate(trial, gid)
                    if not finished:
                        yield [], False
                        return
                    if choice:
                        self.stats['related_fastener_attempts'] += len(related)
                        bundle=[]
                        ids=set(remaining)
                        for fastener in ranked:
                            if fastener in related:
                                bundle.append(self.assign_fastener(ids, fastener, gid))
                                ids.remove(fastener)
                        self.stats['preferred_target_retries'] += 1
                        yield bundle+[choice], True
                        break
                    extra={x for x in blockers if x in remaining and is_fastener(self.groups[x])}-related
                    if not extra:break
                    related |= extra

        fully_explored = True
        yielded = set()
        for bundle, finished in candidates():
            if self.stopped() or not finished:return False, False
            if not bundle:continue
            child = remaining-{c.group_id for c in bundle}
            child_key = frozenset(child)
            if child_key in yielded:
                self.stats['duplicate_group_skips'] += 1
                continue
            yielded.add(child_key)
            if child_key in self.closed:
                self.stats['closed_state_skips'] += 1
                continue
            context.choices.extend(bundle)
            if len(context.choices)>len(context.best_choices):context.best_choices=list(context.choices)
            complete, exhausted = self.visit(child, depth+len(bundle))
            if complete:return True, True
            del context.choices[-len(bundle):]
            fully_explored &= exhausted
            if self.stopped():return False, False
            context.backtracks += 1
            if depth>=self.settings.backtrack_depth or context.backtracks>=self.settings.backtrack_count:
                return False, False
        if fully_explored:self.closed.add(state)
        return False, fully_explored
