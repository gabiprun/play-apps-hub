"""Tests for sync.py's pure ranking logic.

Everything else in sync.py is I/O against the Play API. These cover the two
decisions that shape what the page looks like — which track becomes an app's
headline badge, and what order the cards come out in — so a future refactor
cannot quietly reorder the hub or promote a draft.

Run:  python3 -m pytest test_sync.py -q
"""

import sync


def track(name, *releases):
    return {"track": name, "releases": list(releases)}


def release(version, status="completed"):
    return {"name": version, "status": status}


# --- summarise_tracks -------------------------------------------------------


def test_no_tracks_has_no_best():
    rows, best = sync.summarise_tracks([])
    assert rows == []
    assert best is None


def test_highest_ranked_track_wins_the_badge():
    rows, best = sync.summarise_tracks(
        [
            track("internal", release("1.0.3")),
            track("production", release("1.0.1")),
            track("beta", release("1.0.2")),
        ]
    )
    assert best == (4, "production", "1.0.1")
    assert len(rows) == 3


def test_track_order_in_the_payload_does_not_change_the_winner():
    payload = [
        track("production", release("2.0")),
        track("internal", release("9.9")),
    ]
    _, forwards = sync.summarise_tracks(payload)
    _, backwards = sync.summarise_tracks(list(reversed(payload)))
    assert forwards == backwards == (4, "production", "2.0")


def test_draft_only_tracks_are_skipped_entirely():
    rows, best = sync.summarise_tracks(
        [
            track("production", release("3.0", status="draft")),
            track("internal", release("1.4")),
        ]
    )
    # A draft is not installable: it must neither win the badge nor be listed.
    assert best == (1, "internal", "1.4")
    assert [r["track"] for r in rows] == ["Internal testing"]


def test_a_draft_alongside_a_live_release_does_not_win_within_a_track():
    rows, best = sync.summarise_tracks(
        [track("beta", release("5.0", status="draft"), release("4.9"))]
    )
    assert best == (3, "beta", "4.9")
    assert rows[0]["version"] == "4.9"


def test_empty_release_list_is_skipped():
    rows, best = sync.summarise_tracks([track("production"), track("alpha", release("1.1"))])
    assert best == (2, "alpha", "1.1")
    assert len(rows) == 1


def test_unknown_track_ranks_last_but_is_still_listed():
    rows, best = sync.summarise_tracks(
        [track("qa-sideload", release("0.1")), track("internal", release("1.0"))]
    )
    assert best == (1, "internal", "1.0")
    # Unlabelled tracks fall back to their raw name rather than disappearing.
    assert {r["track"] for r in rows} == {"qa-sideload", "Internal testing"}


def test_an_unknown_track_alone_still_produces_a_best():
    _, best = sync.summarise_tracks([track("qa-sideload", release("0.1"))])
    assert best == (0, "qa-sideload", "0.1")


def test_rows_carry_the_human_label_not_the_api_name():
    rows, _ = sync.summarise_tracks([track("alpha", release("1.0"))])
    assert rows[0] == {"track": "Closed testing", "version": "1.0", "status": "completed"}


# --- app_sort_key -----------------------------------------------------------


def app(title, kind):
    return {"title": title, "statusKind": kind}


def sorted_titles(apps):
    return [a.get("title") for a in sorted(apps, key=sync.app_sort_key)]


def test_production_sorts_above_every_test_track():
    assert sorted_titles(
        [app("Zebra", "production"), app("Alpha", "internal"), app("Beta", "beta")]
    ) == ["Zebra", "Beta", "Alpha"]


def test_same_track_sorts_by_title():
    assert sorted_titles(
        [app("Scrambit", "internal"), app("BoltAway", "internal")]
    ) == ["BoltAway", "Scrambit"]


def test_title_sort_is_case_insensitive():
    # Plain str sort would put every capital ahead of every lowercase.
    assert sorted_titles(
        [app("apple", "internal"), app("Banana", "internal"), app("Cherry", "internal")]
    ) == ["apple", "Banana", "Cherry"]


def test_missing_status_kind_sorts_last_without_raising():
    assert sorted_titles(
        [{"title": "NoTrack"}, app("Live", "production")]
    ) == ["Live", "NoTrack"]


def test_missing_title_does_not_raise():
    assert sorted_titles([{"statusKind": "internal"}, app("Named", "internal")]) == [
        None,
        "Named",
    ]


def test_the_rank_table_orders_the_four_play_tracks_correctly():
    assert (
        sync.TRACK_RANK["production"]
        > sync.TRACK_RANK["beta"]
        > sync.TRACK_RANK["alpha"]
        > sync.TRACK_RANK["internal"]
    )
    # Every ranked track needs a display label, or the badge shows a raw API name.
    assert set(sync.TRACK_RANK) <= set(sync.TRACK_LABEL)
