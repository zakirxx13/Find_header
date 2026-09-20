import asyncio
import json
import os
from datetime import datetime, timezone
from playwright.async_api import async_playwright


TARGET_PAGE = "https://toffeelive.com/en/watch/Xi_Ga5oBNnOkwJLWkhKP"

OUTPUT_DIR = "debug"
API_OUTPUT = os.path.join(OUTPUT_DIR, "api_calls.json")
ERROR_OUTPUT = os.path.join(OUTPUT_DIR, "page_errors.json")
CONSOLE_OUTPUT = os.path.join(OUTPUT_DIR, "console.json")


def mask_headers(headers):
    """
    Keep useful headers but hide sensitive values.
    """
    result = {}

    sensitive = {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "proxy-authorization",
    }

    for key, value in headers.items():
        if key.lower() in sensitive:
            if value:
                result[key] = "[REDACTED]"
            else:
                result[key] = ""
        else:
            result[key] = value

    return result


def safe_json(value):
    try:
        return json.loads(value)
    except Exception:
        return None


async def main():

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    api_calls = []
    page_errors = []
    console_messages = []

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

        # -----------------------------
        # Console
        # -----------------------------

        def on_console(msg):
            try:
                console_messages.append({
                    "type": msg.type,
                    "text": msg.text,
                    "timestamp": datetime.now(
                        timezone.utc
                    ).isoformat()
                })
            except Exception:
                pass

        page.on("console", on_console)

        # -----------------------------
        # Page errors
        # -----------------------------

        def on_page_error(error):
            page_errors.append({
                "error": str(error),
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat()
            })

        page.on("pageerror", on_page_error)

        # -----------------------------
        # Network request
        # -----------------------------

        async def handle_request(request):

            url = request.url

            # Focus on API/playback related requests
            interesting = any(
                x in url.lower()
                for x in [
                    "playback",
                    "entitlement",
                    "toffee",
                    "api"
                ]
            )

            if not interesting:
                return

            payload = request.post_data

            item = {
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),

                "type": "request",

                "url": url,

                "method": request.method,

                "resourceType": request.resource_type,

                "headers": mask_headers(
                    await request.all_headers()
                ),

                "postData": payload,

                "postDataJSON": (
                    safe_json(payload)
                    if payload
                    else None
                )
            }

            api_calls.append(item)

            print("\n================ REQUEST ================")
            print("URL:", url)
            print("METHOD:", request.method)
            print("TYPE:", request.resource_type)

            if payload:
                print("PAYLOAD:")
                print(payload)

        page.on("request", handle_request)

        # -----------------------------
        # Network response
        # -----------------------------

        async def handle_response(response):

            url = response.url

            interesting = any(
                x in url.lower()
                for x in [
                    "playback",
                    "entitlement",
                    "toffee",
                    "api"
                ]
            )

            if not interesting:
                return

            item = {
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),

                "type": "response",

                "url": url,

                "status": response.status,

                "statusText": response.status_text,

                "headers": mask_headers(
                    await response.all_headers()
                )
            }

            # Try to capture response body
            try:
                body = await response.body()

                # Limit extremely large responses
                max_size = 2 * 1024 * 1024

                if len(body) <= max_size:

                    try:
                        text = body.decode(
                            "utf-8",
                            errors="replace"
                        )

                        item["body"] = text

                        parsed = safe_json(text)

                        if parsed is not None:
                            item["bodyJSON"] = parsed

                    except Exception as e:
                        item["bodyError"] = str(e)

                else:
                    item["body"] = (
                        "[Response too large: "
                        + str(len(body))
                        + " bytes]"
                    )

            except Exception as e:
                item["bodyError"] = str(e)

            api_calls.append(item)

            print("\n================ RESPONSE ================")
            print("URL:", url)
            print("STATUS:", response.status)

            if "body" in item:
                print("BODY:")
                print(item["body"][:5000])

        page.on("response", handle_response)

        # -----------------------------
        # Open Toffee
        # -----------------------------

        print("Opening:")
        print(TARGET_PAGE)

        try:

            await page.goto(
                TARGET_PAGE,
                wait_until="domcontentloaded",
                timeout=120000
            )

        except Exception as e:

            page_errors.append({
                "type": "goto",
                "error": str(e),
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat()
            })

        # Wait for initial API calls
        await page.wait_for_timeout(15000)

        # Scroll page to trigger lazy loading
        for _ in range(5):

            await page.mouse.wheel(
                0,
                1200
            )

            await page.wait_for_timeout(
                2500
            )

        # Give remaining requests time
        await page.wait_for_timeout(
            10000
        )

        # -----------------------------
        # Save files
        # -----------------------------

        with open(
            API_OUTPUT,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                {
                    "captured_at": datetime.now(
                        timezone.utc
                    ).isoformat(),

                    "page": TARGET_PAGE,

                    "total_events": len(
                        api_calls
                    ),

                    "events": api_calls
                },
                f,
                ensure_ascii=False,
                indent=2
            )

        with open(
            ERROR_OUTPUT,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                page_errors,
                f,
                ensure_ascii=False,
                indent=2
            )

        with open(
            CONSOLE_OUTPUT,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                console_messages,
                f,
                ensure_ascii=False,
                indent=2
            )

        await browser.close()

    print("\n================================")
    print("DONE")
    print("API events:", len(api_calls))
    print("Output:", API_OUTPUT)
    print("================================")


if __name__ == "__main__":
    asyncio.run(main())
