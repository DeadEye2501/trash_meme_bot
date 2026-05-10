import asyncio
import os
import re

import requests
from bs4 import BeautifulSoup

from parsers.common import build_http_headers, generate_title, logger


PARSE_PINTEREST = bool(int(os.getenv('PARSE_PINTEREST', '0')))
PINTEREST_REGEX = r"(https?://)?(www\.)?((pinterest\.[a-z.]+/pin/[^\s]+)|(pin\.it/[^\s]+))"


async def get_pinterest_content(url, user):
    return await asyncio.to_thread(_get_pinterest_content_sync, url, user)


def _get_pinterest_content_sync(url, user):
    logger.debug("Get pinterest url %s", url)
    match = re.search(PINTEREST_REGEX, url, re.IGNORECASE)
    if match:
        url = match.group(0)
    headers = build_http_headers()
    response = requests.get(url, allow_redirects=True, headers=headers, timeout=30)
    modify_url = response.url
    logger.debug("Get pinterest modify url %s", modify_url)

    soup = BeautifulSoup(response.text, 'html.parser')

    title = generate_title(user, url)
    content = []

    pin_text = None
    title_tag = soup.find('title')
    if title_tag and title_tag.string:
        text_parts = title_tag.string.split('|')
        pin_text = text_parts[0].strip()

    if pin_text:
        content.append({'text': pin_text})

    video_match = re.search(r'https://v\d+\.pinimg\.com/videos/[^"]+\.mp4', response.text)
    if video_match:
        video_url = video_match.group(0)
        content.append({'videos': [video_url]})
    else:
        meta_image = soup.find('meta', property='og:image')
        if meta_image and meta_image.get('content'):
            content.append({'images': [meta_image.get('content')]})

    return title, content
