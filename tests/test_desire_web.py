from __future__ import annotations

from web import _WEB_MODULES
from web import desire as desire_web


class FakeMCP:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, tuple[str, ...]], object] = {}

    def custom_route(self, path: str, methods: list[str]):
        def decorator(fn):
            self.routes[(path, tuple(methods))] = fn
            return fn

        return decorator


def test_desire_state_route_is_part_of_the_registered_web_surface() -> None:
    mcp = FakeMCP()
    desire_web.register(mcp)

    assert ("/api/desire/state", ("GET",)) in mcp.routes
    assert ("web.desire", desire_web.register) in _WEB_MODULES
