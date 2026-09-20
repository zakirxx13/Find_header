import asyncio
import json
import os
from datetime import datetime, timezone

from playwright.async_api import async_playwright


PAGE_URL = "https://toffeelive.com/en/live"

TARGET_PART = "/web/playback/"

OUTPUT_DIR = "debug"

REQUEST_FILE = os.path.join(
    OUTPUT_DIR,
    "playback_request.json"
)

RESPONSE_FILE = os.path.join(
    OUTPUT_DIR,
    "playback_response.json"
)


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
    Hide cookies/auth tokens but keep
    the remaining headers for debugging.
    """

    hidden = {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "proxy-authorization"
    }

    result = {}

    for key, value in headers.items():

        if key.lower() in hidden:
            result[key] = "[REDACTED]"
        else:
            result[key] = value

    return result


async def main():

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    request_saved = False
    response_saved = False

    target_url = None

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        context = await browser.new_context(
            viewport={
                "width": 1280,
                "height": 720
            }
        )

        page = await context.new_page()

        # ==================================================
        # REQUEST
        # ==================================================

        async def on_request(request):

            nonlocal request_saved
            nonlocal target_url

            url = request.url

            if TARGET_PART not in url:
                return

            # Avoid capturing duplicate playback requests
            if request_saved:
                return

            request_saved = True
            target_url = url

            print("")
            print("========================================")
            print("PLAYBACK REQUEST FOUND")
            print("========================================")
            print("URL:", url)
            print("METHOD:", request.method)

            payload = request.post_data

            data = {
                "captured_at": now(),
                "url": url,
                "method": request.method,
                "resourceType": request.resource_type,
                "headers": mask_headers(
                    await request.all_headers()
                ),
                "payload_raw": payload,
                "payload_json": parse_json(payload)
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
            print("REQUEST SAVED:")
            print(REQUEST_FILE)

        # ==================================================
        # RESPONSE
        # ==================================================

        async def on_response(response):

            nonlocal response_saved

            url = response.url

            if TARGET_PART not in url:
                return

            if response_saved:
                return

            response_saved = True

            print("")
            print("========================================")
            print("PLAYBACK RESPONSE FOUND")
            print("========================================")
            print("URL:", url)
            print("STATUS:", response.status)

            data = {
                "captured_at": now(),
                "url": url,
                "status": response.status,
                "statusText": response.status_text,
                "headers": mask_headers(
                    await response.all_headers()
                )
            }

            # ------------------------------------------
            # Read response body
            # ------------------------------------------

            try:

                body = await response.body()

                # 5 MB safety limit
                if len(body) > 5 * 1024 * 1024:

                    data["body_error"] = (
                        "Response larger than 5 MB"
                    )

                else:

                    text = body.decode(
                        "utf-8",
                        errors="replace"
                    )

                    data["response_raw"] = text

                    parsed = parse_json(text)

                    if parsed is not None:
                        data["response_json"] = parsed

            except Exception as e:

                data["body_error"] = str(e)

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
            print("RESPONSE SAVED:")
            print(RESPONSE_FILE)

        page.on(
            "request",
            on_request
        )

        page.on(
            "response",
            on_response
        )

        # ==================================================
        # OPEN TOFFEE
        # ==================================================

        print("")
        print("Opening Toffee:")
        print(PAGE_URL)

        try:

            await page.goto(
                PAGE_URL,
                wait_until="domcontentloaded",
                timeout=120000
            )

        except Exception as e:

            print(
                "Page load warning:",
                str(e)
            )

        # Initial loading
        await page.wait_for_timeout(
            15000
        )

        # ==================================================
        # SCROLL TO TRIGGER LAZY LOADING
        # ==================================================

        for i in range(8):

            print(
                "Scrolling:",
                i + 1,
                "/ 8"
            )

            await page.mouse.wheel(
                0,
                1500
            )

            await page.wait_for_timeout(
                2500
            )

            # Stop once playback request
            # has been captured.
            if request_saved and response_saved:
                break

        # Give response handlers time
        await page.wait_for_timeout(
            5000
        )

        # ==================================================
        # RESULT
        # ==================================================

        print("")
        print("========================================")
        print("CAPTURE FINISHED")
        print("========================================")

        print(
            "Request captured:",
            request_saved
        )

        print(
            "Response captured:",
            response_saved
        )

        if target_url:
            print(
                "Playback URL:",
                target_url
            )

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
