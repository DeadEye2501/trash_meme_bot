import asyncio
import os
import requests
from bs4 import BeautifulSoup

from parsers.common import build_http_headers, generate_title, logger


PARSE_PIKABU = bool(int(os.getenv('PARSE_PIKABU', '0')))
PIKABU_REGEX = r"(https?://)?(www\.)?pikabu\.ru(/[^\s]*)?|link=https%3A%2F%2Fpikabu\.ru%2F[^\s]+"


async def get_pikabu_content(url, user):
    return await asyncio.to_thread(_get_pikabu_content_sync, url, user)


def _get_pikabu_content_sync(url, user):
    logger.debug("Get pikabu url %s", url)
    url_parts = url.split('\n')
    modify_url = url_parts[1] if len(url_parts) > 1 else url_parts[0]
    logger.debug("Get pikabu modify url %s", modify_url)
    response = requests.get(modify_url, headers=build_http_headers(), timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    title = soup.find('h1', class_='story__title')
    title = title.text.strip() if title else 'No Title'
    title = generate_title(user, url, title)

    content = []

    content_blocks = soup.find_all('div', class_='story-block')
    for i, block in enumerate(content_blocks):
        content.append({'text': '', 'images': [], 'videos': []})
        content[i]['text'] = block.get_text(strip=True)

        images = []
        image_blocks = block.find_all('a', class_='image-link')
        for img_block in image_blocks:
            for img in img_block.find_all('img'):
                img_url = img.get('src')
                if not img_url:
                    img_url = img.get('data-src')
                images.append(img_url)
        content[i]['images'] = images

        videos = []
        player_divs = block.find_all('div', class_='player')
        for player_div in player_divs:
            video_sources = ['data-av1', 'data-webm']
            for source in video_sources:
                video_url = player_div.get(source)
                if video_url:
                    videos.append(video_url)
        content[i]['videos'] = videos

    return title, content
