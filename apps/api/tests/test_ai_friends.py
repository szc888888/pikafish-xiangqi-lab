import pytest

from app.ai_friends import _friend, get_friend, load_catalog, random_friend, recommend_friend


def _raw_friend(**overrides):
    raw = {
        "bot_id": "test-friend",
        "name": "测试棋友",
        "avatar_key": "test-friend",
        "description": "用于目录校验测试。",
        "category": "practice",
        "style": ["稳健"],
        "personality": ["耐心"],
        "strength_profile": "progress",
        "config_version": "v1",
        "enabled": True,
        "sort_order": 1,
        "experiences": ["practice"],
    }
    raw.update(overrides)
    return raw


def test_catalog_has_twenty_unique_enabled_ai_friends_with_supported_profiles():
    catalog = load_catalog()

    assert len(catalog.friends) == 20
    assert len({friend.bot_id for friend in catalog.friends}) == 20
    assert all(friend.enabled and friend.is_ai for friend in catalog.friends)
    assert all(friend.strength_profile in {"companion", "beginner", "progress", "serious", "full"} for friend in catalog.friends)


@pytest.mark.parametrize("experience", ["casual", "practice", "challenge"])
def test_recommendation_returns_a_friend_from_requested_experience(experience):
    friend = recommend_friend(experience)

    assert experience in friend.experiences


def test_random_friend_excludes_requested_ids_when_candidates_remain():
    catalog = load_catalog()
    excluded = {friend.bot_id for friend in catalog.friends[:-1]}

    assert random_friend(excluded).bot_id == catalog.friends[-1].bot_id


def test_unknown_friend_id_is_rejected():
    with pytest.raises(KeyError):
        get_friend("not-a-real-bot")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", 1),
        ("avatar_key", "Remote Avatar"),
        ("description", ""),
        ("config_version", "version-1"),
        ("enabled", "false"),
        ("sort_order", "1"),
        ("experiences", "practice"),
        ("style", ["安全", 1]),
    ],
)
def test_invalid_catalog_types_are_rejected(field, value):
    with pytest.raises(ValueError):
        _friend(_raw_friend(**{field: value}))
