"""Live options that preserve the ordinary story-choice callback contract."""

from collections.abc import Callable, Sequence


class RefreshingOptions(Sequence[str]):
    """A sequence for legacy choosers, callable for utility-aware menus.

    The provider is evaluated initially and on each explicit call. Iteration
    reads that coherent tuple, so a selected index matches the route mapping
    built by the provider even when returning from Inventory or Settings.
    """

    def __init__(self, provider: Callable[[], Sequence[str]]) -> None:
        self._provider = provider
        self._options = tuple(provider())

    def __call__(self) -> tuple[str, ...]:
        self._options = tuple(self._provider())
        return self._options

    def __len__(self) -> int:
        return len(self._options)

    def __getitem__(self, index: int | slice) -> str | tuple[str, ...]:
        return self._options[index]
