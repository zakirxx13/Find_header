import asyncio
import json
import os
from datetime import datetime, timezone

from playwright.async_api import async_playwright


# =========================================================
# CONFIG
# =========================================================

# তোমার নিজের LAB endpoint এখানে দাও
LAB_PLAYBACK_URL = "https://toffeelive.com/en/watch/T9O9X5UBm1RY_In7UXFv"

OUTPUT_DIR = "debug"

ORIGINAL_FILE = os.path.join(
    OUTPUT_DIR,
    "original_response.json"
)

MODIFIED_FILE = os.path.join(
    OUTPUT_DIR,
    "modified_response.json"
)

M3U8_FILE = os.path.join(
    OUTPUT_DIR,
    "m3u8_requests.json"
)


# =========================================================
# HELPERS
# =========================================================

def now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def save_json(path, data):
    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# =========================================================
# MAIN
# =========================================================

async def main():

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    m3u8_requests = []

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        context = await browser.new_context(
            viewport={
                "width": 1366,
                "height": 768
            },
            locale="en-US",
            timezone_id="Asia/Dhaka"
        )

        page = await context.new_page()

        # =================================================
        # INTERCEPT ONLY YOUR LAB PLAYBACK ENDPOINT
        # =================================================

        async def handle_route(route, request):

            if request.url != LAB_PLAYBACK_URL:
                await route.continue_()
                return

            print("")
            print("=" * 60)
            print("LAB PLAYBACK REQUEST")
            print("=" * 60)

            print(request.url)

            # Get actual LAB response
            response = await route.fetch()

            body = await response.body()

            try:
                data = json.loads(
                    body.decode(
                        "utf-8",
                        errors="replace"
                    )
                )

            except Exception as e:

                print(
                    "LAB response is not JSON:",
                    e
                )

                await route.fulfill(
                    response=response
                )

                return

            # =================================================
            # SAVE ORIGINAL SERVER RESPONSE
            # =================================================

            original = {
                "captured_at": now(),
                "url": request.url,
                "status": response.status,
                "response": data
            }

            save_json(
                ORIGINAL_FILE,
                original
            )

            print("")
            print("ORIGINAL SERVER RESPONSE:")
            print(
                json.dumps(
                    data,
                    indent=2
                )
            )

            # =================================================
            # LAB-ONLY DENY -> ALLOW SIMULATION
            # =================================================

            modified = dict(data)

            if modified.get("access") == "deny":

                print("")
                print(
                    "LAB TEST: deny -> allow"
                )

                modified["access"] = "allow"

                # Clearly mark this as a local simulation
                modified["lab_simulated"] = True

            else:

                print("")
                print(
                    "Response was already allow."
                )

            # =================================================
            # SAVE MODIFIED RESPONSE
            # =================================================

            modified_output = {
                "captured_at": now(),
                "url": request.url,
                "status": response.status,
                "response": modified
            }

            save_json(
                MODIFIED_FILE,
                modified_output
            )

            print("")
            print("BROWSER WILL RECEIVE:")
            print(
                json.dumps(
                    modified,
                    indent=2
                )
            )

            # =================================================
            # RETURN MODIFIED RESPONSE TO BROWSER
            # =================================================

            await route.fulfill(
                status=response.status,
                headers=dict(response.headers),
                content_type="application/json",
                body=json.dumps(
                    modified
                )
            )

        # =================================================
        # CAPTURE M3U8 REQUESTS
        # =================================================

        async def handle_request(request):

            url = request.url

            if ".m3u8" not in url.lower():
                return

            print("")
            print("=" * 60)
            print("M3U8 REQUEST FOUND")
            print("=" * 60)

            print(url)

            item = {
                "captured_at": now(),
                "url": url,
                "method": request.method,
                "resourceType": request.resource_type
            }

            # Avoid duplicates
            if not any(
                x["url"] == url
                for x in m3u8_requests
            ):

                m3u8_requests.append(
                    item
                )

                save_json(
                    M3U8_FILE,
                    m3u8_requests
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
        # REGISTER ROUTE
        # =================================================

        await page.route(
            LAB_PLAYBACK_URL,
            handle_route
        )

        page.on(
            "request",
            handle_request
        )

        # =================================================
        # OPEN YOUR LAB PLAYER PAGE
        # =================================================

        # যদি playback endpoint-ই test page হয়,
        # সরাসরি endpoint খুলবে।
        #
        # সাধারণত এখানে তোমার নিজের lab player page
        # ব্যবহার করা ভালো।

        print("")
        print("=" * 60)
        print("OPENING LAB PAGE")
        print("=" * 60)

        try:

            await page.goto(
                LAB_PLAYBACK_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

        except Exception as e:

            print("")
            print(
                "Navigation warning:"
            )

            print(e)

        # =================================================
        # WAIT FOR PLAYER / NETWORK
        # =================================================

        print("")
        print(
            "Waiting for LAB player..."
        )

        await page.wait_for_timeout(
            15000
        )

        # =================================================
        # TRY VIDEO PLAY
        # =================================================

        try:

            await page.evaluate(
                """
                () => {
                    document
                        .querySelectorAll("video")
                        .forEach(video => {
                            try {
                                video.muted = true;
                                video.play();
                            } catch(e) {}
                        });
                }
                """
            )

        except Exception as e:

            print(
                "video.play error:",
                e
            )

        # =================================================
        # FINAL WAIT
        # =================================================

        await page.wait_for_timeout(
            15000
        )

        # =================================================
        # FINAL RESULT
        # =================================================

        print("")
        print("=" * 60)
        print("FINAL RESULT")
        print("=" * 60)

        print(
            "M3U8 requests:",
            len(m3u8_requests)
        )

        print("")
        print(
            "Original:",
            ORIGINAL_FILE
        )

        print(
            "Modified:",
            MODIFIED_FILE
        )

        print(
            "M3U8:",
            M3U8_FILE
        )

        await browser.close()


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())
