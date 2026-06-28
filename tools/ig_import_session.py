"""Импорт сессии Instagram в session-файл instaloader.

Зачем: IG закрыл анонимный доступ, а прямой `instaloader --login` упирается в
checkpoint. Надёжный способ — залогиниться в IG в обычном браузере и перенести
куки сессии в session-файл, который читает бот (см. parsers/instagram.py).

Два способа:

1. Из браузера (browser_cookie3):
       python tools/ig_import_session.py [chrome|firefox|edge]   (по умолчанию chrome)
   ВАЖНО: на Chrome/Edge 127+ куки шифруются App-Bound Encryption, и browser_cookie3
   часто вытаскивает ПУСТОЙ sessionid. Если скрипт ругается на это — бери Firefox
   или ручной режим ниже.

2. Вручную (надёжнее всего, работает с любым браузером):
       python tools/ig_import_session.py manual
   Открой instagram.com (залогиненный) → DevTools (F12) → Application → Cookies →
   https://www.instagram.com → скопируй значение cookie `sessionid` и вставь по запросу.

После любого способа скрипт выведет username — пропиши его в .env как INSTAGRAM_USERNAME.

Требует разовой установки:  pip install browser_cookie3
"""
import sys

import instaloader
import requests

_IG_APP_ID = "936619743392459"


def _check_auth(cookies):
    """Вернуть username, если сессия рабочая, иначе None.

    Проверяем через api/v1/accounts/current_user/, а НЕ через instaloader.test_login()
    (тот ходит в graphql, который IG легко отправляет в rate-limit «Please wait a few
    minutes» — и валидная сессия ложно бракуется).
    """
    csrf = next((c.value for c in cookies if c.name == "csrftoken"), "")
    try:
        r = requests.get(
            "https://i.instagram.com/api/v1/accounts/current_user/",
            headers={"X-IG-App-ID": _IG_APP_ID, "X-CSRFToken": csrf,
                     "User-Agent": "Instagram 269.0.0.18.75 Android"},
            cookies=cookies, timeout=30,
        )
        data = r.json()
    except Exception:
        return None
    if data.get("status") == "ok" and data.get("user"):
        return data["user"].get("username")
    return None


def _finish(L):
    """Проверить логин и сохранить сессию."""
    cookies = L.context._session.cookies
    sessionid = next((c.value for c in cookies if c.name == "sessionid"), "")
    if not sessionid:
        sys.exit(
            "Пустой sessionid — куки не прочитались (на Chrome 127+ это типично).\n"
            "Попробуй Firefox или ручной режим:  python tools/ig_import_session.py manual"
        )
    username = _check_auth(cookies)
    if not username:
        # current_user не подтвердил — пробуем штатный test_login (graphql).
        # Может быть под rate-limit'ом, поэтому это запасной, а не основной путь.
        try:
            username = L.test_login()
        except Exception:
            username = None
    if not username:
        sys.exit(
            "sessionid есть, но IG его не принял. Частые причины:\n"
            "  - вход в браузере не подтверждён (IG показывал «Был ли это вы?») — подтверди и повтори;\n"
            "  - скопирован неполный/просроченный sessionid."
        )
    L.context.username = username
    L.save_session_to_file()
    print(f"Готово. Сессия сохранена для @{username}.")
    print(f"Пропиши в .env:  INSTAGRAM_USERNAME={username}")


def _from_browser(browser):
    import browser_cookie3

    browsers = {
        "chrome": browser_cookie3.chrome,
        "firefox": browser_cookie3.firefox,
        "edge": browser_cookie3.edge,
    }
    loader = browsers.get(browser)
    if loader is None:
        sys.exit(f"Неизвестный браузер: {browser}. Доступно: {', '.join(browsers)}")
    cookie_jar = loader(domain_name="instagram.com")
    L = instaloader.Instaloader(save_metadata=False, download_video_thumbnails=False)
    L.context._session.cookies.update(cookie_jar)
    _finish(L)


def _manual():
    sessionid = input("Вставь значение cookie sessionid: ").strip()
    if not sessionid:
        sys.exit("Пустой ввод.")
    L = instaloader.Instaloader(save_metadata=False, download_video_thumbnails=False)
    # ds_user_id — это числовой id перед '%3A'/':' в начале sessionid; нужен IG для авторизации.
    ds_user_id = sessionid.split("%3A")[0].split(":")[0]
    L.context._session.cookies.set("sessionid", sessionid, domain=".instagram.com")
    if ds_user_id.isdigit():
        L.context._session.cookies.set("ds_user_id", ds_user_id, domain=".instagram.com")
    _finish(L)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "chrome"
    if arg == "manual":
        _manual()
    else:
        _from_browser(arg)


if __name__ == "__main__":
    main()
