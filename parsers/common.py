import logging
import os
import random
import string


logger = logging.getLogger('trash_meme_bot')

TEMP_DIR = os.getenv('TEMP_DIR')


def generate_random_string(length=5):
    letters = string.ascii_letters
    return ''.join(random.choice(letters) for _ in range(length))


def escape_markdown(text):
    if not text:
        return text
    escape_chars = ['\\', '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text


def escape_markdown_link_url(url):
    return url.replace('\\', '\\\\').replace(')', '\\)')


def generate_title(user, url, title=None):
    title = f'{escape_markdown(title)}\n' if title else ''
    user_name = escape_markdown(user.full_name) if user.full_name else 'Unknown User'
    return f'{user_name}\n{title}[Посмотреть оригинал]({escape_markdown_link_url(url)})'


def build_http_headers():
    headers = {}
    user_agent = os.getenv('HTTP_USER_AGENT')
    accept_language = os.getenv('HTTP_ACCEPT_LANGUAGE')
    if user_agent:
        headers['User-Agent'] = user_agent
    if accept_language:
        headers['Accept-Language'] = accept_language
    return headers
