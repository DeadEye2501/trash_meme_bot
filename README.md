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
| Twitter/X | `PARSE_X=1`       | playwright (headless Chromium, перехват XHR)        |
| Pinterest | `PARSE_PINTEREST=1` | requests + BeautifulSoup                          |
| Instagram | `PARSE_INSTAGRAM=1` | instaloader (анонимный — IG может вернуть «Этот контент требует авторизации») |

## Установка

* `pip install -r requirements.txt` — установка зависимостей (можно `pipenv install` если используется Pipfile)
* `playwright install chromium` — установка браузера для Twitter-парсера
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

Опционально:

* `HTTP_USER_AGENT`, `HTTP_ACCEPT_LANGUAGE` — заголовки для requests (Pikabu/Pinterest/Reddit)

## Управление (systemd)

* `sudo systemctl start trash_meme_bot` — запуск
* `sudo systemctl stop trash_meme_bot` — остановка
* `sudo systemctl restart trash_meme_bot` — перезапуск
* `sudo systemctl status trash_meme_bot` — статус
* `sudo journalctl -u trash_meme_bot.service -b` — подробные логи
