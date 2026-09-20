import asyncio
import json
import os
from datetime import datetime, timezone

from playwright.async_api import async_playwright


# =========================================================
# CONFIG
# =========================================================

PAGE_URL = (
    "https://toffeelive.com/en/watch/"
    "Xi_Ga5oBNnOkwJLWkhKP"
)

PLAYBACK_PATH = "/web/playback/"

OUTPUT_DIR = "debug"

REQUEST_FILE = os.path.join(
    OUTPUT_DIR,
    "playback_request.json"
)

RESPONSE_FILE = os.path.join(
    OUTPUT_DIR,
    "playback_response.json"
)


# =========================================================
# HELPERS
# =========================================================

def now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def parse_json(value):
    if not value:
        return None

    try:
        return json.loads(value)

    except Exception:
        return None


def mask_headers(headers):
    """
    Hide sensitive authentication/cookie values.
    """

    sensitive = {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "proxy-authorization"
    }

    result = {}

    for key, value in headers.items():

        if key.lower() in sensitive:

            result[key] = "[REDACTED]"

        else:

            result[key] = value

    return result


# =========================================================
# MAIN
# =========================================================

async def main():

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    request_found = False
    response_found = False

    playback_url = None

    async with async_playwright() as p:

        # -------------------------------------------------
        # Browser
        # -------------------------------------------------

        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required"
            ]
        )

        context = await browser.new_context(
            viewport={
                "width": 1366,
                "height": 768
            },

            # Normal browser-like settings
            java_script_enabled=True,

            locale="en-US",

            timezone_id="Asia/Dhaka"
        )

        page = await context.new_page()

        # =================================================
        # REQUEST LISTENER
        # =================================================

        async def handle_request(request):

            nonlocal request_found
            nonlocal playback_url

            url = request.url

            # Only target playback endpoint
            if PLAYBACK_PATH not in url:
                return

            if request_found:
                return

            request_found = True

            playback_url = url

            print("")
            print("=" * 60)
            print("PLAYBACK REQUEST FOUND")
            print("=" * 60)

            print("URL:")
            print(url)

            print("")
            print("METHOD:")
            print(request.method)

            print("")
            print("RESOURCE TYPE:")
            print(request.resource_type)

            # ---------------------------------------------
            # Request payload
            # ---------------------------------------------

            payload = request.post_data

            print("")
            print("PAYLOAD:")

            if payload:
                print(payload)
            else:
                print("[NO POST BODY]")

            # ---------------------------------------------
            # Headers
            # ---------------------------------------------

            try:

                headers = await request.all_headers()

                safe_headers = mask_headers(
                    headers
                )

            except Exception as e:

                safe_headers = {
                    "error": str(e)
                }

            # ---------------------------------------------
            # Save request
            # ---------------------------------------------

            data = {

                "captured_at": now(),

                "url": url,

                "method": request.method,

                "resourceType": request.resource_type,

                "headers": safe_headers,

                "payload_raw": payload,

                "payload_json": parse_json(
                    payload
                )
            }

            with open(
                REQUEST_FILE,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            print("")
            print(
                "Request saved:",
                REQUEST_FILE
            )

        # =================================================
        # RESPONSE LISTENER
        # =================================================

        async def handle_response(response):

            nonlocal response_found

            url = response.url

            # Only target playback endpoint
            if PLAYBACK_PATH not in url:
                return

            if response_found:
                return

            response_found = True

            print("")
            print("=" * 60)
            print("PLAYBACK RESPONSE FOUND")
            print("=" * 60)

            print("URL:")
            print(url)

            print("")
            print("STATUS:")
            print(response.status)

            print("")
            print("STATUS TEXT:")
            print(response.status_text)

            # ---------------------------------------------
            # Response headers
            # ---------------------------------------------

            try:

                headers = await response.all_headers()

                safe_headers = mask_headers(
                    headers
                )

            except Exception as e:

                safe_headers = {
                    "error": str(e)
                }

            data = {

                "captured_at": now(),

                "url": url,

                "status": response.status,

                "statusText": response.status_text,

                "headers": safe_headers
            }

            # ---------------------------------------------
            # Response body
            # ---------------------------------------------

            try:

                body = await response.body()

                print("")
                print(
                    "Response size:",
                    len(body),
                    "bytes"
                )

                # 10 MB limit
                if len(body) <= 10 * 1024 * 1024:

                    text = body.decode(
                        "utf-8",
                        errors="replace"
                    )

                    data["response_raw"] = text

                    parsed = parse_json(
                        text
                    )

                    if parsed is not None:

                        data[
                            "response_json"
                        ] = parsed

                        print("")
                        print(
                            "Response is valid JSON."
                        )

                    else:

                        print("")
                        print(
                            "Response is not JSON."
                        )

                else:

                    data["body_error"] = (
                        "Response body exceeded "
                        "10 MB safety limit."
                    )

            except Exception as e:

                data["body_error"] = str(e)

            # ---------------------------------------------
            # Save response
            # ---------------------------------------------

            with open(
                RESPONSE_FILE,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            print("")
            print(
                "Response saved:",
                RESPONSE_FILE
            )

        # =================================================
        # REGISTER NETWORK LISTENERS
        # =================================================

        page.on(
            "request",
            handle_request
        )

        page.on(
            "response",
            handle_response
        )

        # =================================================
        # PAGE ERRORS
        # =================================================

        page.on(
            "pageerror",
            lambda error: print(
                "[PAGE ERROR]",
                error
            )
        )

        # =================================================
        # OPEN WATCH PAGE
        # =================================================

        print("")
        print("=" * 60)
        print("OPENING WATCH PAGE")
        print("=" * 60)

        print(PAGE_URL)

        try:

            await page.goto(
                PAGE_URL,
                wait_until="domcontentloaded",
                timeout=120000
            )

        except Exception as e:

            print("")
            print(
                "Page navigation warning:"
            )

            print(e)

        # =================================================
        # INITIAL WAIT
        # =================================================

        print("")
        print(
            "Waiting for player initialization..."
        )

        await page.wait_for_timeout(
            15000
        )

        # =================================================
        # PRINT PAGE INFO
        # =================================================

        try:

            print("")
            print("PAGE TITLE:")

            print(
                await page.title()
            )

        except Exception:
            pass

        # =================================================
        # PLAYER / VIDEO DETECTION
        # =================================================

        print("")
        print("=" * 60)
        print("CHECKING PLAYER")
        print("=" * 60)

        selectors = [
            "video",
            "audio",
            "button",
            "[role='button']",
            "[class*='player']",
            "[class*='video']",
            "[class*='play']",
            "[aria-label*='Play']",
            "[aria-label*='play']"
        ]

        for selector in selectors:

            try:

                locator = page.locator(
                    selector
                )

                count = await locator.count()

                print(
                    selector,
                    "=>",
                    count
                )

            except Exception:
                pass

        # =================================================
        # TRY PLAY BUTTONS
        # =================================================

        print("")
        print("=" * 60)
        print("TRYING PLAYER CONTROLS")
        print("=" * 60)

        play_selectors = [

            "button[aria-label*='Play']",

            "button[aria-label*='play']",

            "[role='button'][aria-label*='Play']",

            "[role='button'][aria-label*='play']",

            "[class*='play-button']",

            "[class*='playButton']",

            "[class*='play_button']",

            "[class*='player'] button",

            "video"
        ]

        for selector in play_selectors:

            if request_found:
                break

            try:

                elements = page.locator(
                    selector
                )

                count = await elements.count()

                if count == 0:
                    continue

                print(
                    "Trying selector:",
                    selector,
                    "count:",
                    count
                )

                limit = min(
                    count,
                    5
                )

                for i in range(limit):

                    if request_found:
                        break

                    try:

                        element = elements.nth(i)

                        if not await element.is_visible(
                            timeout=1000
                        ):
                            continue

                        print(
                            "Clicking:",
                            selector,
                            i
                        )

                        await element.click(
                            timeout=5000
                        )

                        await page.wait_for_timeout(
                            5000
                        )

                    except Exception as e:

                        print(
                            "Click failed:",
                            str(e)[:150]
                        )

            except Exception:
                continue

        # =================================================
        # VIDEO PLAY JAVASCRIPT
        # =================================================

        if not request_found:

            print("")
            print(
                "Trying video.play()..."
            )

            try:

                await page.evaluate(
                    """
                    () => {
                        const videos =
                            document.querySelectorAll(
                                "video"
                            );

                        videos.forEach(
                            video => {
                                try {
                                    video.muted = true;
                                    video.play();
                                } catch(e) {}
                            }
                        );
                    }
                    """
                )

                await page.wait_for_timeout(
                    8000
                )

            except Exception as e:

                print(
                    "video.play error:",
                    str(e)
                )

        # =================================================
        # SCROLL
        # =================================================

        if not request_found:

            print("")
            print(
                "Scrolling watch page..."
            )

            for i in range(10):

                if request_found:
                    break

                print(
                    "Scroll",
                    i + 1,
                    "/ 10"
                )

                await page.mouse.wheel(
                    0,
                    1200
                )

                await page.wait_for_timeout(
                    2000
                )

        # =================================================
        # FINAL WAIT
        # =================================================

        print("")
        print(
            "Final network wait..."
        )

        await page.wait_for_timeout(
            10000
        )

        # =================================================
        # FINAL RESULT
        # =================================================

        print("")
        print("=" * 60)
        print("FINAL RESULT")
        print("=" * 60)

        print(
            "Playback request:",
            request_found
        )

        print(
            "Playback response:",
            response_found
        )

        if playback_url:

            print("")
            print(
                "Playback URL:"
            )

            print(
                playback_url
            )

        print("")
        print(
            "Request file:",
            REQUEST_FILE
        )

        print(
            "Response file:",
            RESPONSE_FILE
        )

        # =================================================
        # CLOSE
        # =================================================

        await browser.close()


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
