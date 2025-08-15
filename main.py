import os
import re
import string
import random
import tweepy
import logging
import requests
import asyncpraw
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.audio.io.AudioFileClip import AudioFileClip
from io import BytesIO
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import telegram
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters
from playwright.async_api import async_playwright
import xml.etree.ElementTree as ET
import asyncio
from telegram.error import TimedOut, NetworkError

load_dotenv()

logger = logging.getLogger('trash_meme_bot')
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s [%(name)s] %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

PARSE_PIKABU = bool(int(os.getenv('PARSE_PIKABU')))
PARSE_REDDIT = bool(int(os.getenv('PARSE_REDDIT')))
PARSE_X = bool(int(os.getenv('PARSE_X')))

TEMP_DIR = os.getenv('TEMP_DIR')
TOKEN = os.getenv('TELEGRAM_TOKEN')
REDDIT_REGEX = r"(https?://)?(www\.)?reddit\.com/[^\s]+"
PIKABU_REGEX = r"(https?://)?(www\.)?pikabu\.ru(/[^\s]*)?|link=https%3A%2F%2Fpikabu\.ru%2F[^\s]+"
X_REGEX = r"(https?://)?(www\.)?(x\.com)/[^\s]+"

bot = telegram.Bot(token=TOKEN)

if PARSE_REDDIT:
    reddit = asyncpraw.Reddit(
        client_id=os.getenv('REDDIT_CLIENT_ID'),
        client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
        user_agent=os.getenv('REDDIT_USER_AGENT')
    )

if PARSE_X:
    auth = tweepy.OAuthHandler(os.getenv('X_API_KEY'), os.getenv('X_API_SECRET'))
    auth.set_access_token(os.getenv('X_ACCESS_TOKEN'), os.getenv('X_ACCESS_SECRET'))
    x_api = tweepy.API(auth)


def generate_random_string(length=5):
    letters = string.ascii_letters
    return ''.join(random.choice(letters) for _ in range(length))


def escape_markdown(text):
    if not text:
        return text
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

def generate_title(user, url, title=None):
    title = f'{escape_markdown(title)}\n' if title else ''
    user_name = escape_markdown(user.full_name) if user.full_name else 'Unknown User'
    return f'{user_name}\n{title}[Посмотреть оригинал]({url})'


def parse_mpd_file(mpd_path):
    tree = ET.parse(mpd_path)
    root = tree.getroot()
    namespaces = {'ns': 'urn:mpeg:dash:schema:mpd:2011'}

    max_audio_bandwidth = 0
    max_audio_url = None

    for representation in root.findall('.//ns:AdaptationSet[@contentType="audio"]/ns:Representation', namespaces):
        base_url = representation.find('ns:BaseURL', namespaces).text
        bandwidth = int(representation.get('bandwidth', 0))
        if bandwidth > max_audio_bandwidth:
            max_audio_bandwidth = bandwidth
            max_audio_url = base_url

    return max_audio_url


def download_reddit_video(video_url):
    video_file_name = None
    audio_file_name = None
    mpd_file_name = None
    
    try:
        video_file_name = os.path.join(TEMP_DIR, f'temp_video_{generate_random_string()}.mp4')
        video_response = requests.get(video_url, timeout=30)
        video_response.raise_for_status()
        
        with open(video_file_name, 'wb') as video_file:
            video_file.write(video_response.content)

        if not os.path.exists(video_file_name) or os.path.getsize(video_file_name) == 0:
            raise Exception("Видео файл не был создан или пуст")

        mpd_url = video_url.split("DASH_")[0] + "DASHPlaylist.mpd"
        mpd_file_name = os.path.join(TEMP_DIR, f'temp_playlist_{generate_random_string()}.mpd')
        
        mpd_response = requests.get(mpd_url, timeout=30)
        mpd_response.raise_for_status()
        
        with open(mpd_file_name, 'wb') as f:
            f.write(mpd_response.content)

        audio_url = video_url.split("DASH_")[0] + parse_mpd_file(mpd_file_name)
        if not audio_url:
            return video_file_name

        audio_file_name = os.path.join(TEMP_DIR, f'temp_audio_{generate_random_string()}.mp4')
        audio_response = requests.get(audio_url, timeout=30)
        audio_response.raise_for_status()
        
        with open(audio_file_name, 'wb') as audio_file:
            audio_file.write(audio_response.content)

        if not os.path.exists(audio_file_name) or os.path.getsize(audio_file_name) == 0:
            raise Exception("Аудио файл не был создан или пуст")

        output_file_name = f'compiled_video_{generate_random_string()}.mp4'
        output_path = os.path.join(TEMP_DIR, output_file_name)

        try:
            video_clip = VideoFileClip(video_file_name)
            audio_clip = AudioFileClip(audio_file_name)
            
            if video_clip.duration == 0 or audio_clip.duration == 0:
                raise Exception("Некорректная длительность видео или аудио")
            
            video_clip.audio = audio_clip
            video_clip.write_videofile(
                output_path,
                codec='libx264',
                audio_codec='aac',
                temp_audiofile='temp-audio.m4a',
                remove_temp=True,
                logger=None
            )
            
            video_clip.close()
            audio_clip.close()
        except Exception as e:
            logger.error(f"Ошибка при обработке видео: {str(e)}")
            return video_file_name

        os.remove(video_file_name)
        os.remove(audio_file_name)
        os.remove(mpd_file_name)

        return output_file_name
    except Exception as e:
        logger.error(f"Ошибка при скачивании видео: {str(e)}")
        if video_file_name and os.path.exists(video_file_name):
            os.remove(video_file_name)
        if audio_file_name and os.path.exists(audio_file_name):
            os.remove(audio_file_name)
        if mpd_file_name and os.path.exists(mpd_file_name):
            os.remove(mpd_file_name)
        raise


async def get_pikabu_content(url, user):
    logger.debug(f'Get pikabu url {url}')
    url_parts = url.split('\n')
    modify_url = url_parts[1] if len(url_parts) > 1 else url_parts[0]
    logger.debug(f'Get pikabu modify url {modify_url}')
    response = requests.get(modify_url)
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


async def get_reddit_content(url, user):
    logger.debug(f'Get reddit url {url}')
    response = requests.get(url, allow_redirects=True)
    modify_url = response.url
    logger.debug(f'Get reddit modify url {modify_url}')

    submission = await reddit.submission(url=modify_url)
    title = submission.title
    title = generate_title(user, url, title)
    content = []

    if submission.selftext:
        content.append({'text': submission.selftext})

    if submission.url.endswith(('.jpg', '.jpeg', '.png', '.gif')):
        content.append({'images': [submission.url]})

    is_gallery = getattr(submission, 'is_gallery', False)
    if is_gallery:
        images = [item['media_id'] for item in submission.gallery_data['items']]
        image_urls = [f"https://i.redd.it/{img}.jpg" for img in images]
        content.append({'images': image_urls})

    if submission.media and 'reddit_video' in submission.media:
        video_data = submission.media['reddit_video']
        video_url = video_data['fallback_url']

        try:
            has_audio = video_data.get('has_audio', False)
            if has_audio:
                compiled_video = download_reddit_video(video_url)
                video_temp_path = os.path.join(TEMP_DIR, compiled_video)
                content.append({'video_files': [video_temp_path]})
            else:
                content.append({'videos': [video_url]})
        except Exception as e:
            logger.error(f"Ошибка при обработке видео Reddit: {str(e)}")
            content.append({'videos': [video_url]})

    return title, content


async def get_x_content(url, user):
    logger.debug(f'Get x url {url}')
    _xhr_calls = []
    content = []

    def intercept_response(response):
        if response.request.resource_type == "xhr":
            _xhr_calls.append(response)
        return response

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        page.on("response", intercept_response)
        await page.goto(url, timeout=120000)
        await page.wait_for_selector("[data-testid='tweet']")

        tweet_calls = [f for f in _xhr_calls if "TweetResultByRestId" in f.url]
        for xhr in tweet_calls:
            data = await xhr.json()
            if data:
                title = generate_title(user, url)
                data = data['data']['tweetResult']['result']['legacy']

                if data.get('full_text'):
                    content.append({'text': data['full_text']})

                if data.get('entities'):
                    if data['entities'].get('media'):
                        for item in data['entities']['media']:
                            if item['type'] == 'photo':
                                content.append({'images': [item['media_url_https']]})

                            elif item['type'] == 'video':
                                max_bitrate = 0
                                max_bitrate_variant = 0
                                for num, variant in enumerate(item['video_info']['variants']):
                                    if variant['content_type'] == 'video/mp4':
                                        if 1000000 > variant['bitrate'] > max_bitrate:
                                            max_bitrate = variant['bitrate']
                                            max_bitrate_variant = num
                                content.append(
                                    {'videos': [item['video_info']['variants'][max_bitrate_variant]['url']]})

        await browser.close()
        return title, content


async def retry_send_message(bot, chat_id, text, **kwargs):
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except (TimedOut, NetworkError) as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Попытка {attempt + 1} не удалась: {str(e)}. Повторная попытка через {retry_delay} секунд...")
            await asyncio.sleep(retry_delay)
            retry_delay *= 2


async def process_content(update, title, content):
    try:
        await retry_send_message(
            bot,
            update.message.chat.id,
            title,
            disable_web_page_preview=True,
            parse_mode='Markdown'
        )
        
        for block in content:
            if block.get('text'):
                escaped_text = escape_markdown(block['text'])
                await retry_send_message(
                    bot,
                    update.message.chat.id,
                    escaped_text,
                    disable_web_page_preview=True
                )
            if block.get('images'):
                for img_url in block['images']:
                    try:
                        await bot.send_photo(
                            chat_id=update.message.chat.id,
                            photo=img_url,
                            read_timeout=120,
                            write_timeout=120,
                            connect_timeout=120,
                            pool_timeout=120
                        )
                    except Exception as e:
                        message = f"Не удалось отправить изображение {img_url}\n{str(e)}"
                        logger.error(message)
                        await retry_send_message(bot, update.message.chat.id, escape_markdown(message))
            if block.get('videos'):
                for video_url in block['videos']:
                    try:
                        video_response = requests.get(video_url, timeout=120)
                        video_file = BytesIO(video_response.content)
                        video_file.name = 'video.mp4'
                        await bot.send_video(
                            chat_id=update.message.chat.id,
                            video=video_file,
                            read_timeout=120,
                            write_timeout=120,
                            connect_timeout=120,
                            pool_timeout=120
                        )
                    except Exception as e:
                        message = f"Не удалось отправить видео {video_url}\n{str(e)}"
                        logger.error(message)
                        await retry_send_message(bot, update.message.chat.id, escape_markdown(message))
            if block.get('video_files'):
                for video_file in block['video_files']:
                    try:
                        with open(video_file, 'rb') as f:
                            await bot.send_video(
                                chat_id=update.message.chat.id,
                                video=f,
                                read_timeout=120,
                                write_timeout=120,
                                connect_timeout=120,
                                pool_timeout=120
                            )
                        if os.path.exists(video_file):
                            os.remove(video_file)
                            logger.debug(f"Удален временный файл: {video_file}")
                    except Exception as e:
                        message = f"Не удалось отправить видео файл {video_file}\n{str(e)}"
                        logger.error(message)
                        await retry_send_message(bot, update.message.chat.id, escape_markdown(message))
                        if os.path.exists(video_file):
                            os.remove(video_file)
                            logger.debug(f"Удален временный файл после ошибки: {video_file}")
    except Exception as e:
        error_message = f"Произошла ошибка при обработке контента: {str(e)}"
        logger.error(error_message)
        await retry_send_message(bot, update.message.chat.id, escape_markdown(error_message))


async def check_links(update: Update, context) -> None:
    if not update.message or not update.message.text:
        return
        
    message_text = update.message.text
    user = update.message.from_user
    chat_id = update.message.chat.id

    try:
        if re.search(PIKABU_REGEX, message_text, re.IGNORECASE) and PARSE_PIKABU:
            title, content = await get_pikabu_content(message_text, user)
            await process_content(update, title, content)
            await update.message.delete()

        elif re.search(REDDIT_REGEX, message_text, re.IGNORECASE) and PARSE_REDDIT:
            title, content = await get_reddit_content(message_text, user)
            await process_content(update, title, content)
            await update.message.delete()

        elif re.search(X_REGEX, message_text, re.IGNORECASE) and PARSE_X:
            title, content = await get_x_content(message_text, user)
            await process_content(update, title, content)
            await update.message.delete()
    except Exception as e:
        await bot.send_message(
            chat_id=chat_id, text=f'Не удалось обработать ссылку\n{str(e)}',
            disable_web_page_preview=True
        )


if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_links))
    app.run_polling()
