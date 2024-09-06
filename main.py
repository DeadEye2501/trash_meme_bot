import os
import re
import string
import random
import tweepy
import logging
import requests
import asyncpraw
import moviepy.editor as mpe
from io import BytesIO
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import telegram
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters
import xml.etree.ElementTree as ET

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
PIKABU_REGEX = r"(https?://)?(www\.)?pikabu\.ru/[^\s]+"
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
    video_file_name = os.path.join(os.getenv('TEMP_DIR'), f'temp_video_{generate_random_string()}.mp4')
    with open(video_file_name, 'wb') as video_file:
        video_file.write(requests.get(video_url).content)

    mpd_url = video_url.split("DASH_")[0] + "DASHPlaylist.mpd"
    mpd_file_name = os.path.join(os.getenv('TEMP_DIR'), f'temp_playlist_{generate_random_string()}.mpd')
    with open(mpd_file_name, 'wb') as f:
        f.write(requests.get(mpd_url).content)

    audio_url = video_url.split("DASH_")[0] + parse_mpd_file(mpd_file_name)
    audio_file_name = os.path.join(os.getenv('TEMP_DIR'), f'temp_audio_{generate_random_string()}.mp4')
    with open(audio_file_name, 'wb') as audio_file:
        audio_file.write(requests.get(audio_url).content)

    output_file_name = f'compiled_video_{generate_random_string()}.mp4'

    video_clip = mpe.VideoFileClip(video_file_name)
    audio_clip = mpe.AudioFileClip(audio_file_name)
    final_clip = video_clip.set_audio(audio_clip)
    final_clip.write_videofile(os.path.join(os.getenv('TEMP_DIR'), output_file_name), logger=None)

    os.remove(video_file_name)
    os.remove(audio_file_name)
    os.remove(mpd_file_name)

    return output_file_name


async def get_pikabu_content(url, user):
    logger.debug(f'Get pikabu url {url}')
    url_parts = url.split('\n')
    modify_url = url_parts[1] if len(url_parts) > 1 else url_parts[0]
    logger.debug(f'Get pikabu modify url {modify_url}')
    response = requests.get(modify_url)
    soup = BeautifulSoup(response.text, 'html.parser')

    title = soup.find('h1', class_='story__title')
    title = title.text.strip() if title else 'No Title'
    title = f'[{user.full_name}](tg://user?id={user.id})\n{title}\n[Посмотреть оригинал]({url})'

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
    title = f'[{user.full_name}](tg://user?id={user.id})\n{title}\n[Посмотреть оригинал]({url})'
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

        if video_data['has_audio']:
            compiled_video = download_reddit_video(video_url)
            video_temp_path = os.path.join(os.getenv('TEMP_DIR'), compiled_video)
            content.append({'video_files': [video_temp_path]})
        else:
            content.append({'videos': [video_url]})

    return title, content


async def get_x_content(url, user):
    logger.debug(f'Get x url {url}')
    tweet_id = url.split('/')[-1]
    tweet = x_api.get_status(tweet_id, tweet_mode='extended')

    title = tweet.user.screen_name
    title = f'[{user.full_name}](tg://user?id={user.id})\n{title}\n[Посмотреть оригинал]({url})'
    content = []

    if tweet.full_text:
        content.append({'text': tweet.full_text})

    images = [media['media_url_https'] for media in tweet.entities.get('media', [])]
    if images:
        content.append({'images': images})

    videos = [media['video_info']['variants'][0]['url'] for media in tweet.entities.get('media', []) if
              'video_info' in media]
    if videos:
        content.append({'videos': videos})

    return title, content


async def process_content(update, title, content):
    await bot.send_message(
        chat_id=update.message.chat.id,
        text=title,
        disable_web_page_preview=True,
        parse_mode='Markdown'
    )
    for block in content:
        if block.get('text'):
            await bot.send_message(
                chat_id=update.message.chat.id,
                text=block['text'],
                read_timeout=120,
                write_timeout=120,
                connect_timeout=120,
                pool_timeout=120
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
                    message = f"Can't send image {img_url}\n{e}"
                    logger.debug(message)
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
                    message = f"Can't send video {video_url}\n{e}"
                    logger.debug(message)
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
                except Exception as e:
                    message = f"Can't send video file {video_file}\n{e}"
                    logger.debug(message)


def format_content(content):
    formatted_content = []
    for item in content:
        if item['text']:
            formatted_content.append(item['text'])
        for img in item['images']:
            formatted_content.append(img)
        for vid in item['videos']:
            formatted_content.append(vid)
    return '\n'.join(formatted_content)


async def check_links(update: Update, context) -> None:
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
            chat_id=chat_id, text=f'Не удалось обработать ссылку\n{e}',
            disable_web_page_preview=True
        )


if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_links))
    app.run_polling()
