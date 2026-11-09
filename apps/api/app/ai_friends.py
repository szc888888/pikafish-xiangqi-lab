"""Static AI friend catalog and server-side selection rules."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import secrets
from typing import Any

SUPPORTED_PROFILES = {"companion", "beginner", "progress", "serious", "full"}
EXPERIENCES = {"casual", "practice", "challenge"}


@dataclass(frozen=True)
class AiFriend:
    bot_id: str
    name: str
    avatar_key: str
    description: str
    category: str
    style: tuple[str, ...]
    personality: tuple[str, ...]
    strength_profile: str
    config_version: str
    enabled: bool
    sort_order: int
    experiences: tuple[str, ...]
    is_ai: bool = True


@dataclass(frozen=True)
class AiFriendCatalog:
    catalog_version: str
    friends: tuple[AiFriend, ...]


def _catalog_path() -> Path:
    return Path(__file__).with_name("ai_friends.json")


def _friend(raw: dict[str, Any]) -> AiFriend:
    if not isinstance(raw, dict):
        raise ValueError("AI 棋友配置必须是对象")
    required = {"bot_id", "name", "avatar_key", "description", "category", "style", "personality", "strength_profile", "config_version", "enabled", "sort_order", "experiences"}
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"AI 棋友配置缺少字段: {sorted(missing)}")
    bot_id = raw["bot_id"]
    if not isinstance(bot_id, str) or not bot_id or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in bot_id):
        raise ValueError("AI 棋友 bot_id 无效")
    for field in ("name", "avatar_key", "description", "config_version"):
        value = raw[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"AI 棋友 {bot_id} 的 {field} 无效")
    if re.fullmatch(r"[a-z0-9-]+", raw["avatar_key"]) is None:
        raise ValueError(f"AI 棋友 {bot_id} 的 avatar_key 无效")
    if re.fullmatch(r"v[1-9][0-9]*", raw["config_version"]) is None:
        raise ValueError(f"AI 棋友 {bot_id} 的 config_version 无效")
    if not isinstance(raw["strength_profile"], str) or raw["strength_profile"] not in SUPPORTED_PROFILES:
        raise ValueError(f"AI 棋友 {bot_id} 引用了未知棋力档位")
    if not isinstance(raw["experiences"], list) or any(not isinstance(item, str) for item in raw["experiences"]):
        raise ValueError(f"AI 棋友 {bot_id} 的体验分类无效")
    experiences = tuple(raw["experiences"])
    if not experiences or len(set(experiences)) != len(experiences) or not set(experiences) <= EXPERIENCES:
        raise ValueError(f"AI 棋友 {bot_id} 的体验分类无效")
    if not isinstance(raw["category"], str) or raw["category"] not in EXPERIENCES:
        raise ValueError(f"AI 棋友 {bot_id} 的主分类无效")
    if (
        not isinstance(raw["style"], list)
        or not all(isinstance(item, str) and item.strip() for item in raw["style"])
        or not isinstance(raw["personality"], list)
        or not all(isinstance(item, str) and item.strip() for item in raw["personality"])
    ):
        raise ValueError(f"AI 棋友 {bot_id} 的风格或性格无效")
    if not isinstance(raw["enabled"], bool):
        raise ValueError(f"AI 棋友 {bot_id} 的 enabled 必须是布尔值")
    if isinstance(raw["sort_order"], bool) or not isinstance(raw["sort_order"], int):
        raise ValueError(f"AI 棋友 {bot_id} 的 sort_order 必须是整数")
    return AiFriend(
        bot_id=bot_id,
        name=raw["name"],
        avatar_key=raw["avatar_key"],
        description=raw["description"],
        category=raw["category"],
        style=tuple(raw["style"]),
        personality=tuple(raw["personality"]),
        strength_profile=raw["strength_profile"],
        config_version=raw["config_version"],
        enabled=raw["enabled"],
        sort_order=raw["sort_order"],
        experiences=experiences,
    )


def load_catalog() -> AiFriendCatalog:
    raw = json.loads(_catalog_path().read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("friends"), list):
        raise ValueError("AI 棋友目录结构无效")
    if raw.get("catalog_version") != "v1":
        raise ValueError("AI 棋友目录版本无效")
    friends = tuple(sorted((_friend(item) for item in raw["friends"]), key=lambda item: item.sort_order))
    if len(friends) != 20 or len({friend.bot_id for friend in friends}) != len(friends):
        raise ValueError("AI 棋友目录必须包含 20 个唯一配置")
    return AiFriendCatalog(catalog_version=raw["catalog_version"], friends=friends)


def get_friend(bot_id: str) -> AiFriend:
    friend = next((item for item in load_catalog().friends if item.bot_id == bot_id and item.enabled), None)
    if friend is None:
        raise KeyError(bot_id)
    return friend


def _enabled_for(experience: str) -> list[AiFriend]:
    if experience not in EXPERIENCES:
        raise ValueError("未知的推荐体验")
    return [item for item in load_catalog().friends if item.enabled and experience in item.experiences]


def recommend_friend(experience: str) -> AiFriend:
    candidates = _enabled_for(experience)
    if not candidates:
        raise LookupError("当前体验暂无可用 AI 棋友")
    return secrets.choice(candidates)


def random_friend(exclude_ids: set[str] | None = None) -> AiFriend:
    excluded = exclude_ids or set()
    catalog = load_catalog()
    candidates = [item for item in catalog.friends if item.enabled and item.bot_id not in excluded]
    if not candidates:
        candidates = [item for item in catalog.friends if item.enabled]
    if not candidates:
        raise LookupError("当前没有可用 AI 棋友")
    return secrets.choice(candidates)


def snapshot(friend: AiFriend) -> dict[str, Any]:
    return {
        "bot_id": friend.bot_id,
        "name": friend.name,
        "avatar_key": friend.avatar_key,
        "description": friend.description,
        "category": friend.category,
        "style": list(friend.style),
        "personality": list(friend.personality),
        "strength_profile": friend.strength_profile,
        "config_version": friend.config_version,
        "is_ai": True,
    }
