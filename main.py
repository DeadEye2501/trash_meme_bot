import asyncio
import logging
import os
import re
from collections import namedtuple

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.error import NetworkError, RetryAfter, TimedOut
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest


load_dotenv()

logger = logging.getLogger('trash_meme_bot')
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s [%(name)s] %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN не задан в .env")

# imported after load_dotenv() because parsers read env at module init
from parsers import instagram, pikabu, pinterest, reddit, twitter
from parsers.common import TEMP_DIR, generate_random_string


SEND_TIMEOUTS = dict(read_timeout=120, write_timeout=120, connect_timeout=120, pool_timeout=120)
TELEGRAM_TEXT_LIMIT = 4096


def _chunk_text(text, limit=TELEGRAM_TEXT_LIMIT):
    return [text[i:i + limit] for i in range(0, len(text), limit)] or [text]


ParserSpec = namedtuple('ParserSpec', 'regex enabled func label auth_exc auth_msg', defaults=(None, None))

PARSERS = [
    ParserSpec(pikabu.PIKABU_REGEX, pikabu.PARSE_PIKABU, pikabu.get_pikabu_content, 'Pikabu'),
    ParserSpec(reddit.REDDIT_REGEX, reddit.PARSE_REDDIT, reddit.get_reddit_content, 'Reddit'),
    ParserSpec(twitter.X_REGEX, twitter.PARSE_X, twitter.get_x_content, 'Twitter/X'),
    ParserSpec(pinterest.PINTEREST_REGEX, pinterest.PARSE_PINTEREST, pinterest.get_pinterest_content, 'Pinterest'),
    ParserSpec(
        instagram.INSTAGRAM_REGEX, instagram.PARSE_INSTAGRAM, instagram.get_instagram_content, 'Instagram',
        instagram.InstagramAuthRequired, 'Этот контент требует авторизации',
    ),
]


def _stream_to_temp(url, ext='.mp4'):
    out_path = os.path.join(TEMP_DIR, f"download_{generate_random_string()}{ext}")
    success = False
    try:
        with requests.get(url, timeout=120, stream=True) as r:
            r.raise_for_status()
            with open(out_path, 'wb') as f:
                for chunk in r.iter_content(64 * 1024):
                    if chunk:
                        f.write(chunk)
        success = True
        return out_path
    finally:
        if not success and os.path.exists(out_path):
            os.remove(out_path)


async def retry_send_message(bot, chat_id, text, **kwargs):
    max_retries = 3
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except RetryAfter as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(e.retry_after)
        except (TimedOut, NetworkError):
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(retry_delay)
            retry_delay *= 2


async def _send_url(bot, chat_id, kind, url):
    if kind == 'photo':
        await bot.send_photo(chat_id=chat_id, photo=url, **SEND_TIMEOUTS)
        return
    path = await asyncio.to_thread(_stream_to_temp, url)
    await _send_file(bot, chat_id, 'video', path)


async def _send_file(bot, chat_id, kind, path):
    try:
        with open(path, 'rb') as f:
            if kind == 'photo':
                await bot.send_photo(chat_id=chat_id, photo=f, **SEND_TIMEOUTS)
            else:
                await bot.send_video(chat_id=chat_id, video=f, **SEND_TIMEOUTS)
    finally:
        if os.path.exists(path):
            os.remove(path)


async def _safe_send(bot, chat_id, text, **kwargs):
    try:
        await retry_send_message(bot, chat_id, text, **kwargs)
    except Exception as e:
        logger.error("Не удалось отправить сообщение в чат: %s", e)


async def _report_send_error(bot, chat_id, message):
    logger.error(message)
    await _safe_send(bot, chat_id, message)


async def process_content(bot, update, title, content):
    """Returns True if title and every media item was sent successfully."""
    chat_id = update.message.chat.id
    ok = True

    try:
        await retry_send_message(
            bot, chat_id, title,
            disable_web_page_preview=True, parse_mode='MarkdownV2',
        )
    except Exception as v2_err:
        logger.warning("Title MarkdownV2 failed, falling back to plain: %s", v2_err)
        try:
            await retry_send_message(bot, chat_id, title, disable_web_page_preview=True)
        except Exception as plain_err:
            await _report_send_error(bot, chat_id, f"Не удалось отправить заголовок: {plain_err}")
            ok = False

    try:
        for block in content:
            if block.get('text'):
                for chunk in _chunk_text(block['text']):
                    try:
                        await retry_send_message(bot, chat_id, chunk, disable_web_page_preview=True)
                    except Exception as e:
                        await _report_send_error(bot, chat_id, f"Не удалось отправить текст: {e}")
                        ok = False

            for url in block.get('images') or []:
                try:
                    await _send_url(bot, chat_id, 'photo', url)
                except Exception as e:
                    await _report_send_error(bot, chat_id, f"Не удалось отправить изображение {url}\n{e}")
                    ok = False
            for url in block.get('videos') or []:
                try:
                    await _send_url(bot, chat_id, 'video', url)
                except Exception as e:
                    await _report_send_error(bot, chat_id, f"Не удалось отправить видео {url}\n{e}")
                    ok = False
            for path in block.get('image_files') or []:
                try:
                    await _send_file(bot, chat_id, 'photo', path)
                except Exception as e:
                    await _report_send_error(bot, chat_id, f"Не удалось отправить изображение {path}\n{e}")
                    ok = False
            for path in block.get('video_files') or []:
                try:
                    await _send_file(bot, chat_id, 'video', path)
                except Exception as e:
                    await _report_send_error(bot, chat_id, f"Не удалось отправить видео файл {path}\n{e}")
                    ok = False
    except Exception as e:
        await _report_send_error(bot, chat_id, f"Произошла ошибка при обработке контента: {e}")
        ok = False

    return ok


async def _handle_match(bot, update, spec):
    chat_id = update.message.chat.id
    logger.info("Парсинг %s - начало", spec.label)
    try:
        title, content = await spec.func(update.message.text, update.message.from_user)
    except Exception as e:
        if spec.auth_exc and isinstance(e, spec.auth_exc):
            logger.info("%s - контент требует авторизации", spec.label)
            await _safe_send(bot, chat_id, spec.auth_msg, disable_web_page_preview=True)
            return
        logger.error("ОШИБКА обработки %s: %s", spec.label, e, exc_info=True)
        await _safe_send(
            bot, chat_id, f'Не удалось обработать ссылку\n{e}',
            disable_web_page_preview=True,
        )
        return

    logger.info("Парсинг %s - завершен, блоков: %s", spec.label, len(content))
    ok = await process_content(bot, update, title, content)
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning("Не удалось удалить исходное сообщение: %s", e)
    if ok:
        logger.info("%s - успешно обработано", spec.label)
    else:
        logger.info("%s - обработано с ошибками", spec.label)


async def check_links(update: Update, context) -> None:
    if not update.message or not update.message.text:
        return

    message_text = update.message.text
    user = update.message.from_user
    chat_id = update.message.chat.id

    logger.info(
        "Получено сообщение от %s (ID: %s) в чате %s: %s...",
        user.full_name, user.id, chat_id, message_text[:50],
    )

    for spec in PARSERS:
        if spec.enabled and re.search(spec.regex, message_text, re.IGNORECASE):
            await _handle_match(context.bot, update, spec)
            return


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        logger.warning("Network issue during polling or request: %s", err)
        return
    logger.error(
        "Unhandled exception in handler",
        exc_info=(type(err), err, err.__traceback__) if err else None,
    )


async def _on_shutdown(application):
    await reddit.close()


if __name__ == '__main__':
    request = HTTPXRequest(read_timeout=60, write_timeout=60, connect_timeout=60, pool_timeout=60)
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .request(request)
        .post_shutdown(_on_shutdown)
        .build()
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_links))
    app.add_error_handler(error_handler)
    app.run_polling(allowed_updates=Update.ALL_TYPES)
