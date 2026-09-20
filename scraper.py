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

    name = re.sub(r"[^\w.-]+", "_", path).strip("_")

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
        for match in re.findall(pattern, text, re.IGNORECASE):
            urls.add(match)

    return list(urls)


# =========================================================
# MAIN
# =========================================================

async def main():

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(M3U8_DIR, exist_ok=True)

    if not DEVICE_TOKEN:
        print("ERROR: DEVICE_TOKEN not found!")
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

        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required"
            ]
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
                "Authorization": f"Device {DEVICE_TOKEN}",
            }
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
                    "sameSite": "Lax",
                },
                {
                    "name": "deviceId",
                    "value": DEVICE_TOKEN,
                    "domain": ".toffeelive.com",
                    "path": "/",
                    "secure": True,
                    "sameSite": "Lax",
                }
            ])

            print("✓ Cookies configured")

        except Exception as e:
            print(f"Cookie error: {e}")

        # =================================================
        # STORAGE INITIALIZATION
        # =================================================
        #
        # IMPORTANT:
        # No about:blank navigation.
        # Storage is initialized when a real page is loaded.
        #

        await context.add_init_script(
            """
            (token) => {
                try {
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

                    sessionStorage.setItem(
                        "device_token",
                        token
                    );

                    sessionStorage.setItem(
                        "deviceId",
                        token
                    );

                } catch (e) {
                    console.log(
                        "Storage initialization skipped:",
                        e.message
                    );
                }
            }
            """,
            DEVICE_TOKEN
        )

        print("✓ Storage initialization configured")

        # =================================================
        # PAGE
        # =================================================

        page = await context.new_page()

        # =================================================
        # REQUEST HEADER HANDLER
        # =================================================

        async def add_device_headers(route, request):

            try:

                headers = dict(request.headers)

                if "toffeelive.com" in request.url:

                    headers["X-Device-Token"] = DEVICE_TOKEN
                    headers["X-Device-ID"] = DEVICE_TOKEN

                await route.continue_(headers=headers)

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
        # We only record the server response.
        # We do not modify access/authorization.
        #

        async def log_entitlement(route, request):

            print(
                f"\n[ENTITLEMENT] "
                f"{request.url}"
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
                    "status": status,
                }

                try:

                    text_body = body.decode(
                        "utf-8",
                        errors="ignore"
                    )

                    data = json.loads(text_body)

                    log_entry["response"] = data

                    print(
                        json.dumps(
                            data,
                            indent=2
                        )[:5000]
                    )

                except Exception:

                    log_entry["response_text"] = (
                        body.decode(
                            "utf-8",
                            errors="ignore"
                        )[:5000]
                    )

                entitlement_logs.append(
                    log_entry
                )

                await route.fulfill(
                    status=response.status,
                    headers=dict(response.headers),
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

        async def capture_media(route, request):

            url = request.url
            lower_url = url.lower()

            is_media = any(
                ext in lower_url
                for ext in [
                    ".m3u8",
                    ".mp4",
                    ".ts",
                    ".m4s"
                ]
            )

            if not is_media:

                await route.continue_()
                return

            print(
                f"\n[MEDIA] "
                f"{url[:150]}"
            )

            item = {
                "url": url,
                "type": request.resource_type,
                "time": now(),
            }

            if not any(
                x["url"] == url
                for x in captured_urls
            ):
                captured_urls.append(item)

            # =================================================
            # M3U8
            # =================================================

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
                        f"  Saved: {filepath}"
                    )

                    # =========================================
                    # Extract URLs from playlist
                    # =========================================

                    content = body.decode(
                        "utf-8",
                        errors="ignore"
                    )

                    nested_urls = extract_urls(
                        content
                    )

                    for nested_url in nested_urls:

                        if not any(
                            x["url"] == nested_url
                            for x in captured_urls
                        ):

                            captured_urls.append({
                                "url": nested_url,
                                "type": "from_m3u8",
                                "time": now(),
                            })

                    await route.fulfill(
                        status=response.status,
                        headers=dict(response.headers),
                        body=body
                    )

                    return

                except Exception as e:

                    print(
                        f"  M3U8 capture error: {e}"
                    )

            # =================================================
            # Other media
            # =================================================

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
        # OPEN PAGE
        # =================================================

        print(
            "\n[OPENING]"
        )

        print(CONTENT_URL)

        try:

            await page.goto(
                CONTENT_URL,
                wait_until="domcontentloaded",
                timeout=120000
            )

        except Exception as e:

            print(
                f"\nPage navigation warning: {e}"
            )

        # =================================================
        # PAGE INFO
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
            "\nWaiting for page/player..."
        )

        await page.wait_for_timeout(
            10000
        )

        # =================================================
        # VIDEO PLAY
        # =================================================

        try:

            video_result = await page.evaluate(
                """
                () => {
                    const videos =
                        document.querySelectorAll("video");

                    let results = [];

                    videos.forEach((v, i) => {

                        try {
                            v.muted = true;

                            const p = v.play();

                            if (p) {
                                p.catch(() => {});
                            }

                            results.push({
                                index: i,
                                src: v.src || null,
                                currentSrc:
                                    v.currentSrc || null
                            });

                        } catch (e) {

                            results.push({
                                index: i,
                                error: e.message
                            });

                        }
                    });

                    return results;
                }
                """
            )

            print(
                f"Video elements: "
                f"{len(video_result)}"
            )

        except Exception as e:

            print(
                f"Video play error: {e}"
            )

        # =================================================
        # WAIT FOR MEDIA
        # =================================================

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

        for i, video in enumerate(videos):

            try:

                src = await video.get_attribute(
                    "src"
                )

                current = await video.get_attribute(
                    "currentSrc"
                )

                if src or current:

                    item = {
                        "index": i,
                        "src": src,
                        "currentSrc": current,
                    }

                    video_data.append(item)

                    print(
                        f"  Video {i}: "
                        f"{current or src}"
                    )

            except Exception as e:

                print(
                    f"Video {i} error: {e}"
                )

        # =================================================
        # PERFORMANCE API
        # =================================================

        try:

            perf = await page.evaluate(
                """
                () => {
                    return performance
                        .getEntriesByType("resource")
                        .filter(r =>
                            /\\.(m3u8|mp4|ts|m4s)(\\?|$)/i
                                .test(r.name)
                        )
                        .map(r => ({
                            url: r.name,
                            type: r.initiatorType
                        }));
                }
                """
            )

        except Exception as e:

            print(
                f"Performance API error: {e}"
            )

            perf = []

        print(
            f"\nPerformance API: "
            f"{len(perf)} URLs"
        )

        for item in perf[:20]:

            print(
                f"  - {item['url'][:150]}"
            )

            if not any(
                x["url"] == item["url"]
                for x in captured_urls
            ):

                captured_urls.append({
                    "url": item["url"],
                    "type": (
                        f"perf_"
                        f"{item['type']}"
                    ),
                    "time": now(),
                })

        # =================================================
        # JAVASCRIPT DATA
        # =================================================

        try:

            js_data = await page.evaluate(
                """
                () => {

                    const result = {};

                    [
                        "player",
                        "streamData",
                        "manifest",
                        "sources"
                    ].forEach(key => {

                        try {

                            if (
                                window[key] !== undefined &&
                                window[key] !== null
                            ) {

                                result[key] =
                                    JSON.parse(
                                        JSON.stringify(
                                            window[key]
                                        )
                                    );
                            }

                        } catch (e) {

                            result[key + "_error"] =
                                e.message;
                        }

                    });

                    return result;
                }
                """
            )

        except Exception as e:

            print(
                f"JS extraction error: {e}"
            )

            js_data = {}

        # =================================================
        # STORAGE CHECK
        # =================================================

        try:

            storage_data = await page.evaluate(
                """
                () => {

                    const result = {
                        localStorage: {},
                        sessionStorage: {}
                    };

                    try {

                        for (
                            let i = 0;
                            i < localStorage.length;
                            i++
                        ) {

                            const key =
                                localStorage.key(i);

                            if (
                                key &&
                                /device|token/i.test(key)
                            ) {

                                result.localStorage[key] =
                                    "[PRESENT]";
                            }
                        }

                    } catch (e) {

                        result.localStorage_error =
                            e.message;
                    }

                    try {

                        for (
                            let i = 0;
                            i < sessionStorage.length;
                            i++
                        ) {

                            const key =
                                sessionStorage.key(i);

                            if (
                                key &&
                                /device|token/i.test(key)
                            ) {

                                result.sessionStorage[key] =
                                    "[PRESENT]";
                            }
                        }

                    } catch (e) {

                        result.sessionStorage_error =
                            e.message;
                    }

                    return result;
                }
                """
            )

        except Exception as e:

            storage_data = {
                "error": str(e)
            }

        # =================================================
        # RESULTS
        # =================================================

        results = {
            "captured_at": now(),

            "content_url": CONTENT_URL,

            "final_url": page.url,

            "page_title": title,

            "device_token_used": True,

            "videos_found": len(videos),

            "video_elements": video_data,

            "all_urls": captured_urls,

            "performance_urls": perf,

            "entitlement_logs": entitlement_logs,

            "storage_check": storage_data,

            "js_data": js_data,
        }

        # =================================================
        # SAVE JSON
        # =================================================

        result_path = os.path.join(
            OUTPUT_DIR,
            "results.json"
        )

        with open(
            result_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                results,
                f,
                indent=2,
                ensure_ascii=False
            )

        print(
            "\n" + "=" * 60
        )

        print(
            "DONE"
        )

        print(
            "=" * 60
        )

        print(
            f"✓ Results: {result_path}"
        )

        print(
            f"✓ M3U8 directory: {M3U8_DIR}/"
        )

        print(
            f"✓ Total captured URLs: "
            f"{len(captured_urls)}"
        )

        print(
            f"✓ Entitlement requests: "
            f"{len(entitlement_logs)}"
        )

        # =================================================
        # CLOSE
        # =================================================

        await context.close()
        await browser.close()


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "\nStopped by user."
        )

    except Exception as e:

        print(
            "\nFATAL ERROR:"
        )

        print(
            repr(e)
        )

        raise
