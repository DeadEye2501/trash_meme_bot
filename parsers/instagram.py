import asyncio
import glob
import os
import re
import shutil

import instaloader
from instaloader import Post

from parsers.common import TEMP_DIR, generate_random_string, generate_title, logger


PARSE_INSTAGRAM = bool(int(os.getenv('PARSE_INSTAGRAM', '0')))
INSTAGRAM_REGEX = r"(https?://)?(www\.)?instagram\.com/(reel|reels|p)/[A-Za-z0-9_-]+"


class InstagramAuthRequired(Exception):
    """IG отклонил анонимный запрос (403/login wall) — нужна авторизация."""


def _insta_load_post(normalized_url):
    m = re.search(r'/(?:reels?|p)/([A-Za-z0-9_-]+)', normalized_url, re.I)
    if not m:
        raise ValueError("Неверная ссылка Instagram")
    shortcode = m.group(1)
    out_dir = os.path.abspath(os.path.join(TEMP_DIR, f"insta_{shortcode}_{generate_random_string()}"))
    os.makedirs(out_dir, exist_ok=True)
    dirname_pattern = os.path.join(out_dir, "{target}").replace("\\", "/")
    L = instaloader.Instaloader(
        save_metadata=False,
        download_video_thumbnails=False,
        dirname_pattern=dirname_pattern,
    )
    try:
        post = Post.from_shortcode(L.context, shortcode)
        L.download_post(post, target=shortcode)
    except (
        instaloader.exceptions.BadResponseException,
        instaloader.exceptions.LoginRequiredException,
        instaloader.exceptions.QueryReturnedForbiddenException,
    ) as e:
        raise InstagramAuthRequired() from e
    caption = (post.caption or "").strip()
    content = []
    if caption:
        content.append({"text": caption})
    imgs = []
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        imgs.extend(glob.glob(os.path.join(out_dir, "**", ext), recursive=True))
    vids = []
    for ext in ("*.mp4", "*.webm"):
        vids.extend(glob.glob(os.path.join(out_dir, "**", ext), recursive=True))
    logger.debug("Instagram: out_dir=%s, найдено фото=%s, видео=%s", out_dir, len(imgs), len(vids))
    imgs = [_lift_to_temp_root(p) for p in imgs]
    vids = [_lift_to_temp_root(p) for p in vids]
    shutil.rmtree(out_dir, ignore_errors=True)
    if imgs:
        content.append({"image_files": imgs})
    if vids:
        content.append({"video_files": vids})
    return caption, content


def _lift_to_temp_root(path):
    new_name = f"insta_{generate_random_string()}{os.path.splitext(path)[1]}"
    new_path = os.path.join(TEMP_DIR, new_name)
    shutil.move(path, new_path)
    return new_path


async def get_instagram_content(url, user):
    logger.debug("Get instagram url %s", url)
    m = re.search(INSTAGRAM_REGEX, url, re.IGNORECASE)
    if not m:
        raise ValueError("Ссылка не распознана как Instagram")
    norm = m.group(0).split("?")[0]
    if not norm.startswith("http"):
        norm = "https://www." + norm.lstrip("./")
    caption, content = await asyncio.to_thread(_insta_load_post, norm)
    title = generate_title(user, url)
    return title, content
