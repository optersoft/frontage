"""Hash mode reads only a fragment that is a path (U1): an anchor or a runner's payload is the root."""

from frontage import router


class _Location:
    def __init__(self, hash):
        self.hash = hash


class _History:
    scrollRestoration = "auto"


class _Window:
    def __init__(self, hash):
        self.location = _Location(hash)
        self.history = _History()


def test_hash_mode_treats_a_non_path_fragment_as_the_root(monkeypatch):
    for fragment, expected in (
        ("#/contacts/ann", "/contacts/ann"),
        ("#section", "/"),
        ('#{"code":1}', "/"),
        ("", "/"),
        ("#", "/"),
    ):
        monkeypatch.setattr(router, "window", _Window(fragment))
        assert router.HashMode().current() == expected, fragment
