import fakeredis

from shared.cache.decorator import cached, invalidate_pattern


def _redis():
    return fakeredis.FakeRedis(decode_responses=True)


def test_cached_stores_and_reuses_result():
    calls = {"n": 0}

    @cached(prefix="widgets", ttl=60)
    def expensive(*, redis_client, tenant_id: int):
        calls["n"] += 1
        return {"value": calls["n"]}

    r = _redis()
    assert expensive(redis_client=r, tenant_id=1) == {"value": 1}
    assert expensive(redis_client=r, tenant_id=1) == {"value": 1}
    assert calls["n"] == 1
    assert expensive(redis_client=r, tenant_id=2) == {"value": 2}


def test_invalidate_pattern_deletes_matching_keys():
    r = _redis()
    r.set("ariadesk:shared:widgets:1", "x")
    r.set("ariadesk:shared:widgets:2", "y")
    r.set("ariadesk:shared:other:1", "z")
    deleted = invalidate_pattern(r, "ariadesk:shared:widgets:*")
    assert deleted == 2
    assert r.get("ariadesk:shared:other:1") == "z"
