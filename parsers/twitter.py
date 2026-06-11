import asyncio
import math
import os
import re

import requests

from parsers.common import build_http_headers, generate_title, logger


PARSE_X = bool(int(os.getenv('PARSE_X', '0')))
X_REGEX = r"(https?://)?(www\.|mobile\.)?(twitter\.com|x\.com)/\S*?status/\d+"

_STATUS_ID_REGEX = re.compile(r"(?:twitter\.com|x\.com)/\S*?status/(\d+)", re.IGNORECASE)
_SYNDICATION_URL = "https://cdn.syndication.twimg.com/tweet-result"

# Telegram bot API caps uploads at ~50 MB; keep a margin for the chosen variant.
_VIDEO_SIZE_CAP = 45 * 1024 * 1024
_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")


def _syndication_token(tweet_id):
    """Reproduce the token the embed widget derives from the tweet id."""
    x = (int(tweet_id) / 1e15) * math.pi
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    whole = int(x)
    frac = x - whole
    out = ""
    while whole > 0:
        out = digits[whole % 36] + out
        whole //= 36
    token = out or "0"
    token += "."
    for _ in range(20):
        frac *= 36
        d = int(frac)
        token += digits[d]
        frac -= d
    return re.sub(r"(0+|\.)", "", token)


def _pick_video_url(media):
    info = media.get('video_info') or {}
    variants = [v for v in info.get('variants', []) if v.get('content_type') == 'video/mp4' and v.get('bitrate')]
    if not variants:
        fallback = info.get('variants') or []
        return fallback[0].get('url') if fallback else None

    variants.sort(key=lambda v: v['bitrate'])
    duration_s = (info.get('duration_millis') or 0) / 1000

    best = variants[0]  # lowest quality as a safe default
    for variant in variants:
        if duration_s:
            estimated_bytes = variant['bitrate'] / 8 * duration_s
            if estimated_bytes <= _VIDEO_SIZE_CAP:
                best = variant
        else:
            best = variant  # no duration info — assume short clip, take best quality
    return best.get('url')


def _get_x_content_sync(url, user):
    match = _STATUS_ID_REGEX.search(url)
    if not match:
        raise ValueError("Не удалось извлечь id твита из ссылки")
    tweet_id = match.group(1)
    logger.debug("Get x tweet id %s", tweet_id)

    headers = {'User-Agent': _DEFAULT_UA, **build_http_headers()}
    params = {'id': tweet_id, 'token': _syndication_token(tweet_id), 'lang': 'en'}
    response = requests.get(_SYNDICATION_URL, params=params, headers=headers, timeout=30)
    if response.status_code in (400, 404):
        raise ValueError("Твит не найден, удалён или скрыт")
    response.raise_for_status()
    data = response.json()

    if data.get('__typename') == 'TweetTombstone':
        raise ValueError("Твит недоступен (удалён, защищён или ограничен по возрасту)")

    title = generate_title(user, url)
    content = []

    text = (data.get('text') or '').strip()
    if text:
        content.append({'text': text})

    images = []
    videos = []
    for media in data.get('mediaDetails') or []:
        if media.get('type') == 'photo':
            img = media.get('media_url_https')
            if img:
                images.append(img)
        else:  # video / animated_gif
            video_url = _pick_video_url(media)
            if video_url:
                videos.append(video_url)

    if images:
        content.append({'images': images})
    if videos:
        content.append({'videos': videos})

    logger.debug("X tweet %s: text=%s, images=%s, videos=%s", tweet_id, bool(text), len(images), len(videos))
    return title, content


async def get_x_content(url, user):
    logger.debug("Get x url %s", url)
    return await asyncio.to_thread(_get_x_content_sync, url, user)
