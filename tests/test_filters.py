from __future__ import annotations

from spurline.events import StoredEvent
from spurline.filters import matches_filter, normalize_filters


def test_matches_kind_author_and_tag_filters() -> None:
    event = StoredEvent(
        id="a" * 64,
        pubkey="b" * 64,
        created_at=100,
        kind=1,
        tags=[["e", "root"], ["p", "friend"]],
        content="hello",
        sig="c" * 128,
    )

    assert matches_filter(event, {"authors": ["bbbb"], "kinds": [1], "#p": ["friend"]})
    assert not matches_filter(event, {"authors": ["cccc"]})
    assert not matches_filter(event, {"#p": ["stranger"]})


def test_normalize_filters_drops_unknown_shapes() -> None:
    assert normalize_filters(
        [
            {
                "ids": ["abc"],
                "kinds": [1, "nope"],
                "since": 10,
                "#e": ["root"],
                "#too-long": ["ignored"],
            }
        ]
    ) == [{"ids": ["abc"], "since": 10, "#e": ["root"]}]
