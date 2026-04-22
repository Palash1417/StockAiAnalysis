import pytest

from phase_4_2_prod_wiring.adapters import PgEmbeddingCache
from phase_4_2_prod_wiring.adapters.pg_embedding_cache import _pack, _unpack


def test_roundtrip_pack_unpack():
    vec = [0.1, -0.25, 3.14]
    blob = _pack(vec, 3)
    assert len(blob) == 3 * 4
    out = _unpack(blob, 3)
    assert out == pytest.approx(vec, rel=1e-6)


def test_pack_rejects_wrong_length():
    with pytest.raises(ValueError):
        _pack([0.1, 0.2], 3)


def test_unpack_rejects_wrong_byte_length():
    with pytest.raises(ValueError):
        _unpack(b"\x00" * 7, 2)


def test_put_and_get_roundtrip(connect):
    cache = PgEmbeddingCache(connect)
    vec = [0.1, 0.2, 0.3]
    cache.put_many({"h1": (vec, 3)})
    got = cache.get_many(["h1"])
    assert list(got.keys()) == ["h1"]
    returned_vec, dim = got["h1"]
    assert dim == 3
    assert returned_vec == pytest.approx(vec, rel=1e-6)


def test_get_many_ignores_unknown_hashes(connect):
    cache = PgEmbeddingCache(connect)
    cache.put_many({"h1": ([1.0], 1)})
    got = cache.get_many(["h1", "nope"])
    assert set(got.keys()) == {"h1"}


def test_empty_get_returns_empty(connect):
    assert PgEmbeddingCache(connect).get_many([]) == {}


def test_empty_put_is_noop(connect):
    PgEmbeddingCache(connect).put_many({})


def test_put_updates_existing(connect):
    cache = PgEmbeddingCache(connect)
    cache.put_many({"h1": ([0.1, 0.2], 2)})
    cache.put_many({"h1": ([0.9, 0.8], 2)})
    got = cache.get_many(["h1"])
    assert got["h1"][0] == pytest.approx([0.9, 0.8], rel=1e-6)
