"""Token totals rolled up per local day, small enough to cache on disk.

Two buckets per day: totals per model, and totals per project *and* model. The second
one costs a little more space but lets a project be priced from the models it actually
used - prorating a day's cost by token share would hand real spend to a project whose
model has no published rate.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from . import pricing
from .parser import UsageEvent
from .tokens import ZERO, TokenCounts


def day_key(moment: datetime) -> str:
    """Local-calendar day key: the menu shows days as the user lived them, not as UTC."""
    return moment.astimezone().strftime("%Y-%m-%d")


def day_keys(last_days: int, now: Optional[datetime] = None) -> List[str]:
    """Day keys for the last `last_days` local days, oldest first.

    The arithmetic runs on local calendar dates, not on instants: subtracting 24 hours
    from a fixed-offset timestamp skips a day across a spring DST shift, which would
    silently drop that day's spend out of every total.
    """
    now = now or datetime.now(timezone.utc)
    today = now.astimezone().date()
    days = [today - timedelta(days=offset) for offset in range(max(last_days, 1))]
    return [day.strftime("%Y-%m-%d") for day in reversed(days)]


class UsageAggregate:
    def __init__(
        self,
        by_day_model: Optional[Dict[str, Dict[str, TokenCounts]]] = None,
        by_day_project: Optional[Dict[str, Dict[str, Dict[str, TokenCounts]]]] = None,
    ) -> None:
        #: day -> model -> tokens
        self.by_day_model: Dict[str, Dict[str, TokenCounts]] = defaultdict(dict, by_day_model or {})
        #: day -> project -> model -> tokens
        self.by_day_project: Dict[str, Dict[str, Dict[str, TokenCounts]]] = defaultdict(
            dict, by_day_project or {}
        )

    def add(self, event: UsageEvent) -> None:
        day = day_key(event.timestamp)

        models = self.by_day_model[day]
        models[event.model] = models.get(event.model, ZERO) + event.tokens

        projects = self.by_day_project[day]
        per_model = projects.setdefault(event.project, {})
        per_model[event.model] = per_model.get(event.model, ZERO) + event.tokens

    def extend(self, events) -> None:
        for event in events:
            self.add(event)

    @property
    def is_empty(self) -> bool:
        return not self.by_day_model

    def prune(self, keep_days: List[str]) -> bool:
        """Drops days outside `keep_days`. Returns True when anything was removed."""
        keep = set(keep_days)
        removed = False
        for section in (self.by_day_model, self.by_day_project):
            for day in [day for day in section if day not in keep]:
                del section[day]
                removed = True
        return removed

    def to_dict(self) -> dict:
        return {
            "by_day_model": {
                day: {model: tokens.to_dict() for model, tokens in models.items()}
                for day, models in self.by_day_model.items()
            },
            "by_day_project": {
                day: {
                    project: {model: tokens.to_dict() for model, tokens in models.items()}
                    for project, models in projects.items()
                }
                for day, projects in self.by_day_project.items()
            },
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "UsageAggregate":
        by_day_model = {
            day: {model: TokenCounts.from_dict(tokens) for model, tokens in models.items()}
            for day, models in (raw.get("by_day_model") or {}).items()
        }
        by_day_project = {
            day: {
                project: {model: TokenCounts.from_dict(tokens) for model, tokens in models.items()}
                for project, models in projects.items()
            }
            for day, projects in (raw.get("by_day_project") or {}).items()
        }
        return cls(by_day_model, by_day_project)


@dataclass(frozen=True)
class Slice:
    name: str
    tokens: TokenCounts
    cost: float
    #: True when no published price exists for this model, so `cost` excludes it.
    unpriced: bool = False


@dataclass(frozen=True)
class Summary:
    tokens: TokenCounts = ZERO
    cost: float = 0.0
    cache_savings: float = 0.0
    by_model: List[Slice] = field(default_factory=list)
    by_project: List[Slice] = field(default_factory=list)
    #: (day key, cost) oldest first - the sparkline series.
    daily_costs: List[Tuple[str, float]] = field(default_factory=list)


EMPTY_SUMMARY = Summary()


def summarize(aggregate: UsageAggregate, last_days: int, now: Optional[datetime] = None) -> Summary:
    keys = day_keys(last_days, now)
    wanted = set(keys)

    totals = ZERO
    total_cost = 0.0
    savings = 0.0
    model_tokens: Dict[str, TokenCounts] = {}
    project_tokens: Dict[str, TokenCounts] = {}
    project_cost: Dict[str, float] = {}
    daily: Dict[str, float] = {key: 0.0 for key in keys}

    for day, models in aggregate.by_day_model.items():
        if day not in wanted:
            continue
        for model, tokens in models.items():
            totals = totals + tokens
            model_tokens[model] = model_tokens.get(model, ZERO) + tokens
            model_cost = pricing.cost(tokens, model) or 0.0
            total_cost += model_cost
            daily[day] += model_cost
            savings += pricing.cache_savings(tokens, model) or 0.0

    for day, projects in aggregate.by_day_project.items():
        if day not in wanted:
            continue
        for project, models in projects.items():
            for model, tokens in models.items():
                project_tokens[project] = project_tokens.get(project, ZERO) + tokens
                project_cost[project] = project_cost.get(project, 0.0) + (
                    pricing.cost(tokens, model) or 0.0
                )

    project_slices = sorted(
        (
            Slice(name=name, tokens=tokens, cost=project_cost.get(name, 0.0))
            for name, tokens in project_tokens.items()
        ),
        key=lambda item: (item.cost, item.tokens.total),
        reverse=True,
    )

    model_slices = sorted(
        (
            Slice(
                name=name,
                tokens=tokens,
                cost=pricing.cost(tokens, name) or 0.0,
                unpriced=pricing.rates(name) is None,
            )
            for name, tokens in model_tokens.items()
        ),
        key=lambda item: (item.cost, item.tokens.total),
        reverse=True,
    )

    return Summary(
        tokens=totals,
        cost=total_cost,
        cache_savings=savings,
        by_model=model_slices,
        by_project=project_slices,
        daily_costs=[(key, daily[key]) for key in keys],
    )
