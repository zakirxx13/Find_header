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

DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "")

CONTENT_URL = (
    "https://toffeelive.com/en/watch/"
    "7x0Jd5YBEef-9-uVv_Gy"
)

OUTPUT_DIR = "debug"
M3U8_DIR = os.path.join(OUTPUT_DIR, "m3u8_files")


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
    print(f"Token: {DEVICE_TOKEN[:15]}...{DEVICE_TOKEN[-10:]}")
    
    captured_urls = []
    
    async with async_playwright() as p:
        
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-web-security",
                "--autoplay-policy=no-user-gesture-required"
            ]
        )
        
        # =================================================
        # CONTEXT WITH DEVICE TOKEN
        # =================================================
        
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="Asia/Dhaka",
            extra_http_headers={
                "X-Device-Token": DEVICE_TOKEN,
                "X-Device-ID": DEVICE_TOKEN,
                "Authorization": f"Device {DEVICE_TOKEN}"
            }
        )
        
        # Set device token as cookies (before page creation)
        await context.add_cookies([
            {
                "name": "device_token",
                "value": DEVICE_TOKEN,
                "domain": ".toffeelive.com",
                "path": "/",
                "httpOnly": True,
                "secure": True
            },
            {
                "name": "deviceId",
                "value": DEVICE_TOKEN,
                "domain": ".toffeelive.com",
                "path": "/"
            }
        ])
        
        page = await context.new_page()
        
        # =================================================
        # FIX: Inject localStorage after navigating to blank
        # =================================================
        
        await page.goto("about:blank")
        await page.evaluate(f"""
            () => {{
                localStorage.setItem('device_token', '{DEVICE_TOKEN}');
                localStorage.setItem('deviceId', '{DEVICE_TOKEN}');
                localStorage.setItem('X-Device-Token', '{DEVICE_TOKEN}');
                sessionStorage.setItem('device_token', '{DEVICE_TOKEN}');
                sessionStorage.setItem('deviceId', '{DEVICE_TOKEN}');
            }}
        """)
        print("✓ Device token injected to localStorage")
        
        # =================================================
        # ROUTE HANDLERS
        # =================================================
        
        async def add_device_token(route, request):
            headers = request.headers
            if "toffeelive.com" in request.url:
                headers["X-Device-Token"] = DEVICE_TOKEN
                headers["X-Device-ID"] = DEVICE_TOKEN
            await route.continue_(headers=headers)
        
        await page.route("**/*", add_device_token)
        
        async def modify_entitlement(route, request):
            if "/web/playback/" not in request.url:
                await route.continue_()
                return
            
            print(f"\n[INTERCEPT] {request.url}")
            headers = request.headers
            headers["X-Device-Token"] = DEVICE_TOKEN
            
            try:
                response = await route.fetch(headers=headers)
                body = await response.body()
                
                try:
                    data = json.loads(body.decode("utf-8"))
                    print(f"Original: access={data.get('access')}")
                    
                    data["access"] = "allow"
                    content_id = data.get("id", "")
                    if content_id and "streamUrl" not in data:
                        data["streamUrl"] = f"https://stream.toffeelive.com/{content_id}/master.m3u8"
                        data["manifestUrl"] = f"https://manifest.toffeelive.com/{content_id}/manifest.m3u8"
                    
                    print(f"Modified: access=allow")
                    
                    await route.fulfill(
                        status=response.status,
                        headers=dict(response.headers),
                        body=json.dumps(data)
                    )
                    
                except json.JSONDecodeError:
                    await route.fulfill(
                        status=response.status,
                        headers=dict(response.headers),
                        body=body
                    )
                    
            except Exception as e:
                print(f"Error: {e}")
                await route.abort()
        
        await page.route("**/web/playback/**", modify_entitlement)
        
        async def capture_media(route, request):
            url = request.url
            
            if any(ext in url.lower() for ext in ['.m3u8', '.mp4', '.ts', '.m4s']):
                print(f"\n[MEDIA] {url[:80]}...")
                captured_urls.append({
                    "url": url,
                    "type": request.resource_type,
                    "time": now()
                })
                
                if '.m3u8' in url:
                    try:
                        response = await route.fetch()
                        body = await response.body()
                        
                        filename = re.sub(r'[^\w]', '_', urlparse(url).path)[:80] + ".m3u8"
                        filepath = os.path.join(M3U8_DIR, filename)
                        
                        with open(filepath, "wb") as f:
                            f.write(body)
                        
                        print(f"  Saved: {filename}")
                        
                        content = body.decode('utf-8', errors='ignore')
                        nested = extract_urls(content)
                        for u in nested:
                            if u not in [x["url"] for x in captured_urls]:
                                captured_urls.append({
                                    "url": u,
                                    "type": "from_m3u8",
                                    "time": now()
                                })
                        
                        await route.fulfill(
                            status=response.status,
                            headers=dict(response.headers),
                            body=body
                        )
                        return
                        
                    except Exception as e:
                        print(f"  Error: {e}")
            
            await route.continue_()
        
        await page.route("**/*", capture_media)
        
        # =================================================
        # NOW OPEN CONTENT PAGE
        # =================================================
        
        print(f"\n[OPENING] {CONTENT_URL}")
        
        await page.goto(
            CONTENT_URL,
            wait_until="networkidle",
            timeout=120000
        )
        
        print(f"Title: {await page.title()}")
        
        # Wait and interact
        await page.wait_for_timeout(10000)
        
        await page.evaluate("""
            () => {
                const v = document.querySelector('video');
                if (v) {
                    v.muted = true;
                    v.play().catch(e => {});
                }
            }
        """)
        
        await page.wait_for_timeout(15000)
        
        # =================================================
        # EXTRACT DATA
        # =================================================
        
        print("\n" + "=" * 60)
        print("EXTRACTION")
        print("=" * 60)
        
        videos = await page.query_selector_all("video")
        print(f"Videos: {len(videos)}")
        
        video_data = []
        for i, v in enumerate(videos):
            src = await v.get_attribute("src")
            current = await v.get_attribute("currentSrc")
            if src or current:
                video_data.append({
                    "index": i,
                    "src": src,
                    "currentSrc": current
                })
                print(f"  Video {i}: {current or src}")
        
        perf = await page.evaluate("""
            () => performance.getEntriesByType('resource')
                .filter(r => r.name.match(/\\.(m3u8|mp4|ts|m4s)$/))
                .map(r => ({url: r.name, type: r.initiatorType}))
        """)
        
        print(f"\nPerformance API: {len(perf)} URLs")
        for p in perf[:10]:
            print(f"  - {p['url'][:80]}")
            if p["url"] not in [x["url"] for x in captured_urls]:
                captured_urls.append({
                    "url": p["url"],
                    "type": f"perf_{p['type']}",
                    "time": now()
                })
        
        js_data = await page.evaluate("""
            () => {
                const r = {};
                ['player', 'streamData', 'manifest', 'sources'].forEach(k => {
                    if (window[k]) try {
                        r[k] = JSON.parse(JSON.stringify(window[k]));
                    } catch(e) {}
                });
                return r;
            }
        """)
        
        # =================================================
        # SAVE RESULTS
        # =================================================
        
        results = {
            "captured_at": now(),
            "content_url": CONTENT_URL,
            "device_token_used": True,
            "videos_found": len(videos),
            "video_elements": video_data,
            "all_urls": captured_urls,
            "performance_urls": perf,
            "js_data": js_data
        }
        
        with open(os.path.join(OUTPUT_DIR, "results.json"), "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n✓ Results: {OUTPUT_DIR}/results.json")
        print(f"✓ M3U8 files: {M3U8_DIR}/")
        print(f"✓ Total URLs: {len(captured_urls)}")
        
        await browser.close()


def now():
    return datetime.now(timezone.utc).isoformat()


def extract_urls(text):
    patterns = [
        r'https?://[^\s"\']+\.m3u8[^\s"\']*',
        r'https?://[^\s"\']+\.mp4[^\s"\']*',
        r'https?://[^\s"\']+\.ts[^\s"\']*',
        r'https?://[^\s"\']*manifest[^\s"\']*',
        r'https?://[^\s"\']*playlist[^\s"\']*',
        r'https?://[^\s"\']*stream[^\s"\']*'
    ]
    
    urls = set()
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        urls.update(matches)
    
    return list(urls)


if __name__ == "__main__":
    asyncio.run(main())
