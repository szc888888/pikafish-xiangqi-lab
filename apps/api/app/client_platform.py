"""Coarse, self-reported client usage; never an authentication signal."""

import re

from starlette.requests import Request

CLIENT_PLATFORMS = {"pc", "mini_program", "mobile_web"}


def client_platform(request: Request) -> str:
    supplied = request.headers.get("X-Client-Platform")
    if supplied is not None:
        value = supplied.strip().lower()
        return value if value in CLIENT_PLATFORMS else "unknown"
    agent = request.headers.get("User-Agent", "").lower()
    if re.search(r"\bminiprogram\b", agent):
        return "mini_program"
    if re.search(r"android|iphone|ipad|ipod|mobile", agent):
        return "mobile_web"
    if re.search(r"windows nt|macintosh|x11|cros|linux x86_64", agent):
        return "pc"
    return "unknown"
