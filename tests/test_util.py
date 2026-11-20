"""Run with:  python tests/test_util.py   (no dependencies needed)"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gateway"))
import importlib.util

spec = importlib.util.spec_from_file_location("util", os.path.join(os.path.dirname(__file__), "..", "gateway", "app", "util.py"))
util = importlib.util.module_from_spec(spec)
spec.loader.exec_module(util)

# redaction masks secrets, nested too
assert util.redact({"a": 1, "api_key": "x", "n": {"Password": "p", "ok": 2}, "l": [{"token": "t"}]}) == \
    {"a": 1, "api_key": "[REDACTED]", "n": {"Password": "[REDACTED]", "ok": 2}, "l": [{"token": "[REDACTED]"}]}

# hash chain: same input -> same hash; any change -> different hash; order of keys does not matter
h1 = util.chain_hash(util.GENESIS, {"a": 1, "b": 2})
assert h1 == util.chain_hash(util.GENESIS, {"b": 2, "a": 1})
assert h1 != util.chain_hash(util.GENESIS, {"a": 1, "b": 3})
assert h1 != util.chain_hash("1" * 64, {"a": 1, "b": 2})

# version extraction
assert util.body_version(b'{"id":"r1","version":4}') == "4"
assert util.body_version(b"hello", {"etag": '"abc"'}) == "abc"
assert util.body_version(b"hello").startswith("h:")
assert util.body_version(b"hello") == util.body_version(b"hello")
assert util.body_version(b"hello") != util.body_version(b"hellp")

# parsing
assert util.parse_json(b"") is None and util.parse_json(b"not json") is None
assert util.parse_json(b'{"x":1}') == {"x": 1}
print("util tests passed")
