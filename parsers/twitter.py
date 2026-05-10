import os

from playwright.async_api import async_playwright

from parsers.common import generate_title


PARSE_X = bool(int(os.getenv('PARSE_X', '0')))
X_REGEX = r"(https?://)?(www\.)?(x\.com)/[^\s]+"


async def get_x_content(url, user):
    _xhr_calls = []
    content = []
    title = generate_title(user, url)

    def intercept_response(response):
        if response.request.resource_type in ("xhr", "fetch"):
            _xhr_calls.append(response)
        return response

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(viewport={"width": 1920, "height": 1080})
            page = await context.new_page()

            page.on("response", intercept_response)
            try:
                async with page.expect_response(
                    lambda r: "TweetResultByRestId" in r.url,
                    timeout=15000,
                ):
                    await page.goto(url, timeout=120000)
            except Exception:
                pass
            await page.wait_for_selector("[data-testid='tweet']")

            tweet_calls = [f for f in _xhr_calls if "TweetResultByRestId" in f.url]
            processed_tweets = set()

            for xhr in tweet_calls:
                data = await xhr.json()
                if data:
                    tweet_id = data['data']['tweetResult']['result'].get('rest_id')
                    if tweet_id in processed_tweets:
                        continue
                    processed_tweets.add(tweet_id)
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
        finally:
            await browser.close()
        return title, content
