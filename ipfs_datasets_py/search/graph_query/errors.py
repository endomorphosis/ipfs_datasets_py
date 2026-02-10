class GraphQueryError(Exception):
    """Base class for graph-query failures."""


class QueryRejectedError(GraphQueryError):
    """Raised when a query is rejected by policy (e.g., unanchored scan)."""

    def to_dict(self) -> dict:
        return {
            "type": self.__class__.__name__,
            "message": str(self),
        }


class BudgetExceededError(GraphQueryError):
    """Raised when execution exceeds a configured budget."""

    def __init__(
        self,
        message: str,
        *,
        budget: str | None = None,
        actual: int | float | None = None,
        limit: int | float | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.budget = budget
        self.actual = actual
        self.limit = limit
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "type": self.__class__.__name__,
            "message": str(self),
            "budget": self.budget,
            "actual": self.actual,
            "limit": self.limit,
            "detail": self.detail,
        }

    @classmethod
    def exceeded(
        cls,
        budget: str,
        *,
        actual: int | float,
        limit: int | float,
        unit: str | None = None,
        detail: str | None = None,
    ) -> "BudgetExceededError":
        suffix = f"{unit}" if unit else ""
        msg = f"{budget} exceeded ({actual}{suffix} > {limit}{suffix})"
        return cls(msg, budget=budget, actual=actual, limit=limit, detail=detail)
