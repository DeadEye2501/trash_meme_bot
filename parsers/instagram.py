import asyncio
import os
import re
import threading

import instaloader
import requests
from instaloader import Post

from parsers.common import TEMP_DIR, generate_random_string, generate_title, logger


PARSE_INSTAGRAM = bool(int(os.getenv('PARSE_INSTAGRAM', '0')))
INSTAGRAM_REGEX = r"(https?://)?(www\.)?instagram\.com/(reel|reels|p)/[A-Za-z0-9_-]+"

# IG закрыл анонимный доступ — нужен вход под аккаунтом (session-файл instaloader).
INSTAGRAM_USERNAME = (os.getenv('INSTAGRAM_USERNAME') or '').strip()
INSTAGRAM_PASSWORD = (os.getenv('INSTAGRAM_PASSWORD') or '').strip()
INSTAGRAM_SESSIONFILE = (os.getenv('INSTAGRAM_SESSIONFILE') or '').strip() or None

# Официальный graphql/doc_id у instaloader 4.15.1 IG отклоняет (403) даже с логином,
# поэтому пост тянем через приватный web-API api/v1/media/<id>/info/ с куками сессии.
_IG_APP_ID = "936619743392459"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# media_type из ответа IG.
_MEDIA_IMAGE = 1
_MEDIA_VIDEO = 2
_MEDIA_CAROUSEL = 8

# Ошибки instaloader при загрузке сессии, означающие «нужна авторизация».
_AUTH_EXCEPTIONS = (
    instaloader.exceptions.BadResponseException,
    instaloader.exceptions.LoginRequiredException,
    instaloader.exceptions.QueryReturnedForbiddenException,
    instaloader.exceptions.ConnectionException,
)

# Сессия создаётся один раз и переиспользуется; обращения к ней сериализуются.
_lock = threading.Lock()
_loader = None


class InstagramAuthRequired(Exception):
    """IG отклонил запрос (403/login wall) или нет рабочей сессии — нужна авторизация."""


def _get_loader_locked():
    """Вернуть авторизованный Instaloader (вызывать под _lock)."""
    global _loader
    if _loader is not None:
        return _loader
    if not INSTAGRAM_USERNAME:
        raise InstagramAuthRequired(
            "INSTAGRAM_USERNAME не задан — анонимный доступ к Instagram закрыт"
        )
    L = instaloader.Instaloader(save_metadata=False, download_video_thumbnails=False)
    logged_in_by_password = False
    try:
        L.load_session_from_file(INSTAGRAM_USERNAME, INSTAGRAM_SESSIONFILE)
        logger.info("Instagram: сессия загружена для @%s", INSTAGRAM_USERNAME)
    except FileNotFoundError as e:
        if not INSTAGRAM_PASSWORD:
            raise InstagramAuthRequired(
                f"Нет session-файла Instagram. Выполни один раз вход: "
                f"instaloader --login {INSTAGRAM_USERNAME}"
            ) from e
        logger.info("Instagram: session-файл не найден, вход по паролю @%s", INSTAGRAM_USERNAME)
        L.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
        logged_in_by_password = True
    # Пустой sessionid = нерабочая сессия. Две частые причины:
    #  1) вход по паролю с сервера — IG ставит checkpoint и выдаёт ds_user_id, но НЕ sessionid;
    #  2) импорт кук из Chrome 127+, где они зашифрованы App-Bound Encryption.
    # С таким файлом IG редиректит на логин и всё рушится — отсекаем сразу.
    sessionid = next(
        (c.value for c in L.context._session.cookies if c.name == "sessionid"), ""
    )
    if not sessionid:
        if logged_in_by_password:
            raise InstagramAuthRequired(
                "Instagram принял пароль, но не выдал сессию (checkpoint: требует "
                "подтверждения входа). Войди в IG в браузере, подтверди «это вы», и "
                "импортируй сессию: python tools/ig_import_session.py firefox"
            )
        raise InstagramAuthRequired(
            "В session-файле Instagram нет рабочего sessionid — переимпортируй сессию "
            "(python tools/ig_import_session.py firefox)"
        )
    # Сессия с sessionid — сохраняем (на случай свежего логина) и переиспользуем.
    if logged_in_by_password:
        L.save_session_to_file(INSTAGRAM_SESSIONFILE)
        logger.info("Instagram: вход выполнен, сессия сохранена")
    _loader = L
    return _loader


def _csrf_token(cookies):
    """Достать csrftoken из jar, где может быть несколько одноимённых кук (разные домены).

    cookies.get() падает с CookieConflictError при дубликатах (так бывает после
    свежего L.login() — токен заводится сразу на .instagram.com и i.instagram.com),
    поэтому итерируемся вручную и предпочитаем куку основного домена.
    """
    token = ""
    for c in cookies:
        if c.name == "csrftoken":
            token = c.value
            if (c.domain or "").lstrip(".") == "instagram.com":
                return c.value
    return token


def _media_info(loader, media_id, shortcode):
    """Запросить api/v1/media/<id>/info/ с куками сессии. Вернуть dict первого item."""
    cookies = loader.context._session.cookies
    headers = {
        "User-Agent": _UA,
        "X-IG-App-ID": _IG_APP_ID,
        "X-CSRFToken": _csrf_token(cookies),
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/p/{shortcode}/",
        "Accept": "*/*",
    }
    url = f"https://www.instagram.com/api/v1/media/{media_id}/info/"
    r = requests.get(url, headers=headers, cookies=cookies, timeout=30)
    if r.status_code in (401, 403):
        raise InstagramAuthRequired(f"Instagram отклонил запрос ({r.status_code})")
    # При недействительной сессии IG не отдаёт 401, а редиректит (200) на HTML-страницу
    # логина. Ловим это до r.json(), иначе падаем с «Expecting value: line 1 column 1».
    if "/accounts/login" in r.url or "application/json" not in r.headers.get("content-type", ""):
        raise InstagramAuthRequired(
            "Instagram вернул страницу логина — сессия недействительна, переимпортируй её"
        )
    r.raise_for_status()
    items = (r.json() or {}).get("items") or []
    if not items:
        raise ValueError("Instagram не вернул данные поста (удалён или приватный)")
    return items[0]


def _media_urls(node):
    """Вернуть (kind, url) для одиночного узла (фото/видео)."""
    versions = node.get("video_versions")
    if versions:
        return "video", versions[0]["url"]
    candidates = node["image_versions2"]["candidates"]
    return "image", candidates[0]["url"]  # первый — максимальное разрешение


def _collect_media(item):
    """Список (kind, url) для поста: учитывает карусель."""
    nodes = item.get("carousel_media") or [item]
    return [_media_urls(n) for n in nodes]


def _download(url, ext):
    path = os.path.join(TEMP_DIR, f"insta_{generate_random_string()}{ext}")
    success = False
    try:
        with requests.get(url, headers={"User-Agent": _UA}, timeout=120, stream=True) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(64 * 1024):
                    if chunk:
                        f.write(chunk)
        success = True
        return path
    finally:
        if not success and os.path.exists(path):
            os.remove(path)


def _insta_load_post(normalized_url):
    global _loader
    m = re.search(r'/(?:reels?|p)/([A-Za-z0-9_-]+)', normalized_url, re.I)
    if not m:
        raise ValueError("Неверная ссылка Instagram")
    shortcode = m.group(1)
    media_id = Post.shortcode_to_mediaid(shortcode)
    with _lock:
        try:
            loader = _get_loader_locked()
            item = _media_info(loader, media_id, shortcode)
        except _AUTH_EXCEPTIONS as e:
            _loader = None  # сессия могла протухнуть — пересоздадим при следующей попытке
            raise InstagramAuthRequired(str(e) or "Instagram отклонил запрос") from e
        except InstagramAuthRequired:
            _loader = None
            raise
    caption = ((item.get("caption") or {}).get("text") or "").strip()
    media = _collect_media(item)
    logger.debug("Instagram: shortcode=%s, медиа=%s", shortcode, len(media))
    imgs, vids = [], []
    for kind, url in media:
        if kind == "video":
            vids.append(_download(url, ".mp4"))
        else:
            imgs.append(_download(url, ".jpg"))
    content = []
    if caption:
        content.append({"text": caption})
    if imgs:
        content.append({"image_files": imgs})
    if vids:
        content.append({"video_files": vids})
    return caption, content


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
