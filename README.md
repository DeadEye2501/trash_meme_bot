# Trash Meme Bot

Этот бот существует для того, чтобы сделать вашу переписку в телеграме с друзьями, где вы скидываете друг другу мемы,
более интерактивной и похожей на ленту. Просто добавьте бота в группу и дайте ему права администратора.

## Источники

Бот ловит ссылки в чате и переотправляет содержимое поста (текст, картинки, видео) от имени отправителя. Поддерживаемые
источники и переключатели в `.env`:

| Источник  | Флаг              | Технология                                          |
|-----------|-------------------|-----------------------------------------------------|
| Pikabu    | `PARSE_PIKABU=1`  | requests + BeautifulSoup                            |
| Reddit    | `PARSE_REDDIT=1`  | asyncpraw (нужны `REDDIT_CLIENT_*`) + ffmpeg/moviepy для видео |
| Twitter/X | `PARSE_X=1`       | requests (официальный embed-эндпоинт `cdn.syndication.twimg.com`) |
| Pinterest | `PARSE_PINTEREST=1` | requests + BeautifulSoup                          |
| Instagram | `PARSE_INSTAGRAM=1` | instaloader (нужен вход под аккаунтом — IG закрыл анонимный доступ) |

## Установка

* `pip install -r requirements.txt` — установка зависимостей (можно `pipenv install` если используется Pipfile)
* скопировать `.env.example` в `.env` и заполнить токены и пути
* для systemd скопировать `meme_bot.service` в `/etc/systemd/system/`
* для Windows положить `autostart_meme_bot.bat` в `shell:startup`
  (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`)

## Конфигурация

Минимально обязательное в `.env`:

* `TELEGRAM_TOKEN` — токен от @BotFather
* `TEMP_DIR` — куда складывать временные файлы (видео из Reddit/IG)
* `PARSE_*` — какие источники включить (`1` или `0`)
* `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` — если включён `PARSE_REDDIT`
* `INSTAGRAM_USERNAME` — если включён `PARSE_INSTAGRAM` (анонимный доступ IG закрыл, посты
  тянутся через приватный web-API с куками сессии). Сессию надёжнее всего перенести из
  браузера: залогинься в instagram.com, закрой браузер и выполни
  `pip install browser_cookie3` + `python tools/ig_import_session.py [chrome|firefox|edge]`.
  Скрипт сохранит session-файл и подскажет, какой `INSTAGRAM_USERNAME` вписать в `.env`.
  Аккаунт может быть техническим. Сессия живёт месяцами; когда протухнет, бот ответит
  «Этот контент требует авторизации» — просто переимпортируй сессию тем же скриптом.

Опционально:

* `INSTAGRAM_SESSIONFILE` — путь к session-файлу, если он лежит не в стандартном месте instaloader
* `INSTAGRAM_PASSWORD` — вход по логину/паролю при первом запуске (нежелательно: IG часто
  требует checkpoint и выше риск временной блокировки; импорт из браузера надёжнее)

* `HTTP_USER_AGENT`, `HTTP_ACCEPT_LANGUAGE` — заголовки для requests (Pikabu/Pinterest/Reddit)

## Управление (systemd)

* `sudo systemctl start trash_meme_bot` — запуск
* `sudo systemctl stop trash_meme_bot` — остановка
* `sudo systemctl restart trash_meme_bot` — перезапуск
* `sudo systemctl status trash_meme_bot` — статус
* `sudo journalctl -u trash_meme_bot.service -b` — подробные логи
