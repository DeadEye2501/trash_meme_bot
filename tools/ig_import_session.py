"""Импорт сессии Instagram из браузера в session-файл instaloader.

Зачем: IG закрыл анонимный доступ, а прямой `instaloader --login` упирается в
checkpoint. Надёжный способ — залогиниться в IG в обычном браузере и перенести
куки сессии в session-файл, который читает бот (см. parsers/instagram.py).

Использование:
    1. Залогинься в instagram.com в браузере, чтобы лента открывалась.
    2. Закрой браузер (иначе база куки может быть заблокирована).
    3. Запусти:  python tools/ig_import_session.py [chrome|firefox|edge]
       (по умолчанию chrome)
    4. Скрипт выведет username — пропиши его в .env как INSTAGRAM_USERNAME.

Требует разовой установки:  pip install browser_cookie3
"""
import sys

import browser_cookie3
import instaloader

BROWSERS = {
    "chrome": browser_cookie3.chrome,
    "firefox": browser_cookie3.firefox,
    "edge": browser_cookie3.edge,
}


def main():
    browser = sys.argv[1] if len(sys.argv) > 1 else "chrome"
    loader = BROWSERS.get(browser)
    if loader is None:
        sys.exit(f"Неизвестный браузер: {browser}. Доступно: {', '.join(BROWSERS)}")

    cookie_jar = loader(domain_name="instagram.com")
    if "sessionid" not in {c.name for c in cookie_jar}:
        sys.exit("Не найден sessionid — залогинься в Instagram в этом браузере и повтори.")

    L = instaloader.Instaloader(save_metadata=False, download_video_thumbnails=False)
    L.context._session.cookies.update(cookie_jar)
    username = L.test_login()
    if not username:
        sys.exit("Куки есть, но IG их не принял — войди в аккаунт заново в браузере.")

    L.context.username = username
    L.save_session_to_file()
    print(f"Готово. Сессия сохранена. Пропиши в .env:  INSTAGRAM_USERNAME={username}")


if __name__ == "__main__":
    main()
