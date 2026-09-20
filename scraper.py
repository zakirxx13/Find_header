import asyncio
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.async_api import async_playwright


# =========================================================
# CONFIG
# =========================================================

DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "").strip()

CONTENT_URL = (
    "https://toffeelive.com/en/watch/"
    "7x0Jd5YBEef-9-uVv_Gy"
)

OUTPUT_DIR = "debug"
M3U8_DIR = os.path.join(OUTPUT_DIR, "m3u8_files")


# =========================================================
# HELPERS
# =========================================================

def now():
    return datetime.now(timezone.utc).isoformat()


def safe_filename(url, extension=".m3u8"):
    path = urlparse(url).path

    name = re.sub(
        r"[^\w.-]+",
        "_",
        path
    ).strip("_")

    if not name:
        name = "playlist"

    name = name[:120]

    if not name.endswith(extension):
        name += extension

    return name


def extract_urls(text):
    patterns = [
        r'https?://[^\s"\']+\.m3u8[^\s"\']*',
        r'https?://[^\s"\']+\.mp4[^\s"\']*',
        r'https?://[^\s"\']+\.ts[^\s"\']*',
        r'https?://[^\s"\']*manifest[^\s"\']*',
        r'https?://[^\s"\']*playlist[^\s"\']*',
        r'https?://[^\s"\']*stream[^\s"\']*',
    ]

    urls = set()

    for pattern in patterns:
        matches = re.findall(
            pattern,
            text,
            re.IGNORECASE
        )

        urls.update(matches)

    return list(urls)


# =========================================================
# MAIN
# =========================================================

async def main():

    # =====================================================
    # DIRECTORIES
    # =====================================================

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    os.makedirs(
        M3U8_DIR,
        exist_ok=True
    )

    # =====================================================
    # DEVICE TOKEN
    # =====================================================

    if not DEVICE_TOKEN:

        print(
            "ERROR: DEVICE_TOKEN not found!"
        )

        return

    print("=" * 60)
    print("TOFFEE DEVICE TOKEN SCRAPER")
    print("=" * 60)

    print(
        f"Token: "
        f"{DEVICE_TOKEN[:15]}..."
        f"{DEVICE_TOKEN[-10:]}"
    )

    captured_urls = []
    entitlement_logs = []

    async with async_playwright() as p:

        # =================================================
        # BROWSER
        # =================================================

        print(
            "\nLaunching Chromium..."
        )

        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required"
            ]
        )

        print(
            "✓ Chromium launched"
        )

        # =================================================
        # CONTEXT
        # =================================================

        context = await browser.new_context(

            viewport={
                "width": 1366,
                "height": 768
            },

            locale="en-US",

            timezone_id="Asia/Dhaka",

            extra_http_headers={
                "X-Device-Token": DEVICE_TOKEN,
                "X-Device-ID": DEVICE_TOKEN,
                "Authorization":
                    f"Device {DEVICE_TOKEN}"
            }
        )

        print(
            "✓ Browser context created"
        )

        # =================================================
        # COOKIES
        # =================================================

        try:

            await context.add_cookies([

                {
                    "name": "device_token",

                    "value": DEVICE_TOKEN,

                    "domain": ".toffeelive.com",

                    "path": "/",

                    "httpOnly": True,

                    "secure": True,

                    "sameSite": "Lax"
                },

                {
                    "name": "deviceId",

                    "value": DEVICE_TOKEN,

                    "domain": ".toffeelive.com",

                    "path": "/",

                    "httpOnly": False,

                    "secure": True,

                    "sameSite": "Lax"
                }

            ])

            print(
                "✓ Cookies configured"
            )

        except Exception as e:

            print(
                f"Cookie configuration error: {e}"
            )

        # =================================================
        # STORAGE INITIALIZATION
        # =================================================
        #
        # IMPORTANT:
        # Do NOT navigate to about:blank and access
        # localStorage.
        #
        # The token is embedded safely into the init script.
        #

        storage_token = json.dumps(
            DEVICE_TOKEN
        )

        try:

            await context.add_init_script(
                script=f"""
                (() => {{
                    const token = {storage_token};

                    try {{
                        localStorage.setItem(
                            "device_token",
                            token
                        );

                        localStorage.setItem(
                            "deviceId",
                            token
                        );

                        localStorage.setItem(
                            "X-Device-Token",
                            token
                        );

                    }} catch (e) {{
                        console.log(
                            "localStorage initialization skipped:",
                            e.message
                        );
                    }}

                    try {{
                        sessionStorage.setItem(
                            "device_token",
                            token
                        );

                        sessionStorage.setItem(
                            "deviceId",
                            token
                        );

                    }} catch (e) {{
                        console.log(
                            "sessionStorage initialization skipped:",
                            e.message
                        );
                    }}
                }})();
                """
            )

            print(
                "✓ Storage initialization configured"
            )

        except Exception as e:

            print(
                f"Storage initialization error: {e}"
            )

        # =================================================
        # PAGE
        # =================================================

        page = await context.new_page()

        print(
            "✓ Page created"
        )

        # =================================================
        # DEVICE HEADER ROUTE
        # =================================================

        async def add_device_headers(
            route,
            request
        ):

            try:

                headers = dict(
                    request.headers
                )

                if (
                    "toffeelive.com"
                    in request.url
                ):

                    headers[
                        "X-Device-Token"
                    ] = DEVICE_TOKEN

                    headers[
                        "X-Device-ID"
                    ] = DEVICE_TOKEN

                await route.continue_(
                    headers=headers
                )

            except Exception as e:

                print(
                    f"[HEADER ERROR] {e}"
                )

                try:

                    await route.continue_()

                except Exception:
                    pass

        await page.route(
            "**/*",
            add_device_headers
        )

        # =================================================
        # ENTITLEMENT LOGGER
        # =================================================
        #
        # Only logs the server response.
        # It does NOT modify authorization/access.
        #

        async def log_entitlement(
            route,
            request
        ):

            print(
                "\n[ENTITLEMENT]"
            )

            print(
                request.url
            )

            try:

                response = await route.fetch()

                body = await response.body()

                status = response.status

                print(
                    f"Status: {status}"
                )

                log_entry = {
                    "time": now(),
                    "url": request.url,
                    "status": status
                }

                try:

                    text_body = body.decode(
                        "utf-8",
                        errors="ignore"
                    )

                    data = json.loads(
                        text_body
                    )

                    log_entry[
                        "response"
                    ] = data

                    print(
                        json.dumps(
                            data,
                            indent=2,
                            ensure_ascii=False
                        )[:5000]
                    )

                except Exception:

                    log_entry[
                        "response_text"
                    ] = body.decode(
                        "utf-8",
                        errors="ignore"
                    )[:5000]

                entitlement_logs.append(
                    log_entry
                )

                await route.fulfill(
                    status=response.status,
                    headers=dict(
                        response.headers
                    ),
                    body=body
                )

            except Exception as e:

                print(
                    f"[ENTITLEMENT ERROR] {e}"
                )

                try:

                    await route.continue_()

                except Exception:
                    pass

        await page.route(
            "**/web/playback/**",
            log_entitlement
        )

        # =================================================
        # MEDIA CAPTURE
        # =================================================

        async def capture_media(
            route,
            request
        ):

            url = request.url

            lower_url = url.lower()

            media_extensions = [
                ".m3u8",
                ".mp4",
                ".ts",
                ".m4s"
            ]

            is_media = any(
                ext in lower_url
                for ext in media_extensions
            )

            if not is_media:

                await route.continue_()

                return

            print(
                "\n[MEDIA]"
            )

            print(
                url[:200]
            )

            if not any(
                item["url"] == url
                for item in captured_urls
            ):

                captured_urls.append({

                    "url": url,

                    "type":
                        request.resource_type,

                    "time": now()
                })

            # =============================================
            # M3U8
            # =============================================

            if ".m3u8" in lower_url:

                try:

                    response = await route.fetch()

                    body = await response.body()

                    filename = safe_filename(
                        url,
                        ".m3u8"
                    )

                    filepath = os.path.join(
                        M3U8_DIR,
                        filename
                    )

                    with open(
                        filepath,
                        "wb"
                    ) as f:

                        f.write(body)

                    print(
                        f"M3U8 saved: {filepath}"
                    )

                    # -------------------------------------
                    # Extract URLs from playlist
                    # -------------------------------------

                    content = body.decode(
                        "utf-8",
                        errors="ignore"
                    )

                    nested_urls = extract_urls(
                        content
                    )

                    for nested_url in nested_urls:

                        if not any(
                            item["url"]
                            == nested_url
                            for item
                            in captured_urls
                        ):

                            captured_urls.append({

                                "url":
                                    nested_url,

                                "type":
                                    "from_m3u8",

                                "time":
                                    now()
                            })

                    await route.fulfill(
                        status=response.status,
                        headers=dict(
                            response.headers
                        ),
                        body=body
                    )

                    return

                except Exception as e:

                    print(
                        f"M3U8 capture error: {e}"
                    )

            # =============================================
            # Other media
            # =============================================

            try:

                await route.continue_()

            except Exception as e:

                print(
                    f"Media continue error: {e}"
                )

        await page.route(
            "**/*",
            capture_media
        )

        # =================================================
        # OPEN CONTENT PAGE
        # =================================================

        print(
            "\n" + "=" * 60
        )

        print(
            "OPENING CONTENT PAGE"
        )

        print(
            "=" * 60
        )

        print(
            CONTENT_URL
        )

        navigation_error = None

        try:

            await page.goto(
                CONTENT_URL,
                wait_until="domcontentloaded",
                timeout=120000
            )

        except Exception as e:

            navigation_error = str(e)

            print(
                f"Navigation warning: {e}"
            )

        # =================================================
        # PAGE INFORMATION
        # =================================================

        try:

            title = await page.title()

        except Exception:

            title = ""

        print(
            f"\nTitle: {title}"
        )

        print(
            f"Current URL: {page.url}"
        )

        # =================================================
        # WAIT
        # =================================================

        print(
            "\nWaiting 10 seconds..."
        )

        await page.wait_for_timeout(
            10000
        )

        # =================================================
        # PLAY VIDEOS
        # =================================================

        video_play_result = []

        try:

            video_play_result = (
                await page.evaluate(
                    """
                    () => {

                        const videos =
                            document.querySelectorAll(
                                "video"
                            );

                        const result = [];

                        videos.forEach(
                            (video, index) => {

                                try {

                                    video.muted = true;

                                    const promise =
                                        video.play();

                                    if (promise) {
                                        promise.catch(
                                            () => {}
                                        );
                                    }

                                    result.push({

                                        index: index,

                                        src:
                                            video.src
                                            || null,

                                        currentSrc:
                                            video.currentSrc
                                            || null
                                    });

                                } catch (e) {

                                    result.push({

                                        index: index,

                                        error:
                                            e.message
                                    });
                                }
                            }
                        );

                        return result;
                    }
                    """
                )
            )

            print(
                f"Video elements detected: "
                f"{len(video_play_result)}"
            )

        except Exception as e:

            print(
                f"Video play error: {e}"
            )

        # =================================================
        # WAIT FOR MEDIA REQUESTS
        # =================================================

        print(
            "\nWaiting 15 seconds for media..."
        )

        await page.wait_for_timeout(
            15000
        )

        # =================================================
        # EXTRACTION
        # =================================================

        print(
            "\n" + "=" * 60
        )

        print(
            "EXTRACTION"
        )

        print(
            "=" * 60
        )

        # =================================================
        # VIDEO ELEMENTS
        # =================================================

        videos = await page.query_selector_all(
            "video"
        )

        print(
            f"Videos found: {len(videos)}"
        )

        video_data = []

        for index, video in enumerate(
            videos
        ):

            try:

                src = await video.get_attribute(
                    "src"
                )

                current_src = (
                    await video.get_attribute(
                        "currentSrc"
                    )
                )

                if src or current_src:

                    item = {

                        "index": index,

                        "src": src,

                        "currentSrc":
                            current_src
                    }

                    video_data.append(
                        item
                    )

                    print(
                        f"Video {index}: "
                        f"{current_src or src}"
                    )

            except Exception as e:

                print(
                    f"Video {index} error: {e}"
                )

        # =================================================
        # PERFORMANCE API
        # =================================================

        try:

            performance_urls = (
                await page.evaluate(
                    """
                    () 
