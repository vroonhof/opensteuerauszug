from opensteuerauszug.importers.common import SecurityNameRegistry
from opensteuerauszug.model.position import SecurityPosition


def _pos(symbol="AAPL", description=None):
    return SecurityPosition(depot="D1", symbol=symbol, description=description)


def test_higher_priority_wins():
    registry = SecurityNameRegistry()
    p = _pos()
    registry.update(p, "low", priority=1)
    registry.update(p, "high", priority=5)
    registry.update(p, "mid", priority=3)
    assert registry.best(p) == "high"


def test_tie_keeps_existing():
    registry = SecurityNameRegistry()
    p = _pos()
    registry.update(p, "first", priority=5)
    registry.update(p, "second", priority=5)
    assert registry.best(p) == "first"


def test_resolve_falls_back_to_description_then_symbol():
    registry = SecurityNameRegistry()
    with_desc = _pos(symbol="AAPL", description="Apple Inc")
    without_desc = _pos(symbol="MSFT")
    # no name stored yet
    assert registry.resolve(with_desc) == "Apple Inc"
    assert registry.resolve(without_desc) == "MSFT"
    # once a registered name is present, it wins
    registry.update(with_desc, "Apple Inc (AAPL)", priority=10)
    assert registry.resolve(with_desc) == "Apple Inc (AAPL)"
