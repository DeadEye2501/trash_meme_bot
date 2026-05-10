import asyncio
import os
import subprocess
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import asyncpraw
import imageio_ffmpeg
import requests
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.video.io.VideoFileClip import VideoFileClip

from parsers.common import TEMP_DIR, build_http_headers, generate_random_string, generate_title, logger


PARSE_REDDIT = bool(int(os.getenv('PARSE_REDDIT', '0')))
REDDIT_REGEX = r"(https?://)?(www\.)?reddit\.com/[^\s]+"


if PARSE_REDDIT:
    reddit_client = asyncpraw.Reddit(
        client_id=os.getenv('REDDIT_CLIENT_ID'),
        client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
        user_agent=os.getenv('REDDIT_USER_AGENT')
    )


async def close():
    if PARSE_REDDIT:
        await reddit_client.close()


def parse_mpd_file(mpd_path):
    tree = ET.parse(mpd_path)
    root = tree.getroot()
    namespaces = {'ns': 'urn:mpeg:dash:schema:mpd:2011'}

    max_audio_bandwidth = 0
    max_audio_url = None

    for representation in root.findall('.//ns:AdaptationSet[@contentType="audio"]/ns:Representation', namespaces):
        base_url_elem = representation.find('ns:BaseURL', namespaces)
        if base_url_elem is None or not base_url_elem.text:
            continue
        bandwidth = int(representation.get('bandwidth', 0))
        if bandwidth > max_audio_bandwidth:
            max_audio_bandwidth = bandwidth
            max_audio_url = base_url_elem.text

    return max_audio_url


def download_reddit_video(video_url, hls_url=None):
    video_file_name = None
    audio_file_name = None
    mpd_file_name = None

    try:
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

        if hls_url:
            output_file_name = f'compiled_video_{generate_random_string()}.mp4'
            output_path = os.path.join(TEMP_DIR, output_file_name)
            result = subprocess.run(
                [
                    ffmpeg_path,
                    "-y",
                    "-i",
                    hls_url,
                    "-map", "0:v:0",
                    "-map", "0:a:0",
                    "-c", "copy",
                    output_path,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.stderr:
                logger.debug("FFmpeg output: %s", result.stderr)
            return output_path

        video_file_name = os.path.join(TEMP_DIR, f'temp_video_{generate_random_string()}.mp4')
        video_response = requests.get(video_url, timeout=30)
        video_response.raise_for_status()

        with open(video_file_name, 'wb') as video_file:
            video_file.write(video_response.content)

        if not os.path.exists(video_file_name) or os.path.getsize(video_file_name) == 0:
            raise Exception("Видео файл не был создан или пуст")

        if "DASH_" not in video_url:
            return video_file_name

        mpd_url = video_url.split("DASH_")[0] + "DASHPlaylist.mpd"
        mpd_file_name = os.path.join(TEMP_DIR, f'temp_playlist_{generate_random_string()}.mpd')

        mpd_response = requests.get(mpd_url, timeout=30)
        mpd_response.raise_for_status()

        with open(mpd_file_name, 'wb') as f:
            f.write(mpd_response.content)

        audio_relative = parse_mpd_file(mpd_file_name)
        if not audio_relative:
            if os.path.exists(mpd_file_name):
                os.remove(mpd_file_name)
            return video_file_name
        audio_url = video_url.split("DASH_")[0] + audio_relative

        audio_file_name = os.path.join(TEMP_DIR, f'temp_audio_{generate_random_string()}.mp4')
        audio_response = requests.get(audio_url, timeout=30)
        audio_response.raise_for_status()

        with open(audio_file_name, 'wb') as audio_file:
            audio_file.write(audio_response.content)

        if not os.path.exists(audio_file_name) or os.path.getsize(audio_file_name) == 0:
            raise Exception("Аудио файл не был создан или пуст")

        output_path = os.path.join(TEMP_DIR, f'compiled_video_{generate_random_string()}.mp4')
        temp_audio_path = os.path.join(TEMP_DIR, f'temp-audio-{generate_random_string()}.m4a')

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
                temp_audiofile=temp_audio_path,
                remove_temp=True,
                logger=None
            )

            video_clip.close()
            audio_clip.close()
        except Exception as e:
            logger.error("Ошибка при обработке видео: %s", e)
            for leftover in (audio_file_name, mpd_file_name):
                if leftover and os.path.exists(leftover):
                    os.remove(leftover)
            return video_file_name

        os.remove(video_file_name)
        os.remove(audio_file_name)
        os.remove(mpd_file_name)

        return output_path
    except Exception as e:
        logger.error("Ошибка при скачивании видео: %s", e)
        if video_file_name and os.path.exists(video_file_name):
            os.remove(video_file_name)
        if audio_file_name and os.path.exists(audio_file_name):
            os.remove(audio_file_name)
        if mpd_file_name and os.path.exists(mpd_file_name):
            os.remove(mpd_file_name)
        raise


async def get_reddit_content(url, user):
    logger.debug("Get reddit url %s", url)
    response = await asyncio.to_thread(
        requests.get, url, allow_redirects=True, headers=build_http_headers(), timeout=30,
    )
    response.raise_for_status()
    modify_url = response.url
    logger.debug("Get reddit modify url %s", modify_url)

    submission = await reddit_client.submission(url=modify_url)
    title = submission.title
    title = generate_title(user, url, title)
    content = []

    if submission.selftext:
        content.append({'text': submission.selftext})

    if submission.url and urlparse(submission.url).path.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
        content.append({'images': [submission.url]})

    is_gallery = getattr(submission, 'is_gallery', False)
    if is_gallery:
        gallery_images = []
        gallery_videos = []
        media_meta = getattr(submission, 'media_metadata', {}) or {}
        gallery_items = (getattr(submission, 'gallery_data', None) or {}).get('items') or []
        for item in gallery_items:
            meta = media_meta.get(item.get('media_id'), {})
            source = meta.get('s', {})
            kind = meta.get('e', 'Image')
            if kind == 'Image':
                u = source.get('u')
                if u:
                    gallery_images.append(u.replace('&amp;', '&'))
            else:  # AnimatedImage / RedditVideo
                u = source.get('mp4') or source.get('gif')
                if u:
                    gallery_videos.append(u.replace('&amp;', '&'))
        if gallery_images:
            content.append({'images': gallery_images})
        if gallery_videos:
            content.append({'videos': gallery_videos})

    if submission.media and 'reddit_video' in submission.media:
        video_data = submission.media['reddit_video'] or {}
        video_url = video_data.get('fallback_url')
        hls_url = video_data.get('hls_url')

        if video_url:
            try:
                compiled_video_path = await asyncio.to_thread(download_reddit_video, video_url, hls_url=hls_url)
                content.append({'video_files': [compiled_video_path]})
            except Exception as e:
                logger.error("Ошибка при обработке видео Reddit: %s", e)
                content.append({'videos': [video_url]})

    return title, content
