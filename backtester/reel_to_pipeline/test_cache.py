from reel_to_pipeline.cache import compute_cache_key, find_cached_outcome
from database import SessionLocal, init_db
import models


def test_cache_key_is_stable_regardless_of_param_order():
    ir_a = {"strategy": "DCA", "params": {"a": 1, "b": 2}}
    ir_b = {"strategy": "DCA", "params": {"b": 2, "a": 1}}
    assert compute_cache_key(ir_a, "BTC/USDT", "1d") == compute_cache_key(ir_b, "BTC/USDT", "1d")


def test_cache_key_differs_on_symbol_or_timeframe():
    ir = {"strategy": "DCA", "params": {"a": 1}}
    k1 = compute_cache_key(ir, "BTC/USDT", "1d")
    k2 = compute_cache_key(ir, "ETH/USDT", "1d")
    k3 = compute_cache_key(ir, "BTC/USDT", "4h")
    assert len({k1, k2, k3}) == 3


def test_find_cached_outcome_hit_and_miss():
    init_db()
    db = SessionLocal()
    ir = {"strategy": "DCA", "params": {"buy_interval_hours": 24}}
    key = compute_cache_key(ir, "BTC/USDT", "1d")
    try:
        assert find_cached_outcome(db, key) is None  # miss before insert

        row = models.StrategyOutcome(
            strategy="DCA", symbol="BTC/USDT", params='{"buy_interval_hours": 24}',
        )
        # cache_key isn't a StrategyOutcome column — the lookup matches on
        # strategy+symbol+params directly, so build the row the same way.
        db.add(row)
        db.commit()

        hit = find_cached_outcome(db, key)
        assert hit is not None
        assert hit.strategy == "DCA"
    finally:
        db.query(models.StrategyOutcome).filter_by(strategy="DCA", symbol="BTC/USDT").delete()
        db.commit()
        db.close()
