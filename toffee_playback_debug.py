import asyncio
import json
import os
from datetime import datetime, timezone

from playwright.async_api import async_playwright


# =========================================================
# CONFIG
# =========================================================

# GitHub Secrets থেকে auth_session লোড
AUTH_SESSION = os.environ.get("AUTH_SESSION", "")

CONTENT_URL = (
    "https://toffeelive.com/en/watch/"
    "7x0Jd5YBEef-9-uVv_Gy"
)

OUTPUT_DIR = "debug"


# =========================================================
# MAIN
# =========================================================

async def main():
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    if not AUTH_SESSION:
        print("ERROR: AUTH_SESSION not found in environment!")
        return
    
    print("=" * 60)
    print("TOFFEE SESSION AUTH SCRAPER")
    print("=" * 60)
    print(f"Auth Session: {AUTH_SESSION[:20]}...{AUTH_SESSION[-10:]}")
    
    async with async_playwright() as p:
        
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-web-security"]
        )
        
        # =================================================
        # SETUP CONTEXT WITH AUTH SESSION
        # =================================================
        
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="Asia/Dhaka",
            
            # Inject auth via extra headers
            extra_http_headers={
                "Authorization": f"Bearer {AUTH_SESSION}",
                "X-Auth-Session": AUTH_SESSION
            }
        )
        
        # Set auth_session as cookie
        await context.add_cookies([
            {
                "name": "auth_session",
                "value": AUTH_SESSION,
                "domain": ".toffeelive.com",
                "path": "/",
                "httpOnly": True,
                "secure": True
            },
            {
                "name": "session",
                "value": AUTH_SESSION,
                "domain": ".toffeelive.com",
                "path": "/"
            },
            {
                "name": "token",
                "value": AUTH_SESSION,
                "domain": ".toffeelive.com",
                "path": "/"
            }
        ])
        
        page = await context.new_page()
        
        # =================================================
        # INJECT SESSION TO LOCALSTORAGE
        # =================================================
        
        await page.evaluate(f"""
            () => {{
                // Common storage keys
                localStorage.setItem('auth_session', '{AUTH_SESSION}');
                localStorage.setItem('session', '{AUTH_SESSION}');
                localStorage.setItem('token', '{AUTH_SESSION}');
                localStorage.setItem('access_token', '{AUTH_SESSION}');
                localStorage.setItem('authToken', '{AUTH_SESSION}');
                
                sessionStorage.setItem('auth_session', '{AUTH_SESSION}');
                sessionStorage.setItem('session', '{AUTH_SESSION}');
            }}
        """)
        
        print("✓ Auth session injected to cookies and localStorage")
        
        # =================================================
        # ROUTE MODIFICATION (Deny → Allow)
        # =================================================
        
        async def modify_entitlement(route, request):
            
            if "/web/playback/" not in request.url:
                await route.continue_()
                return
            
            print(f"\n[INTERCEPT] {request.url}")
            
            # Add auth header to request
            headers = request.headers
            headers["Authorization"] = f"Bearer {AUTH_SESSION}"
            
            try:
                response = await route.fetch(headers=headers)
                body = await response.body()
                
                try:
                    data = json.loads(body.decode("utf-8"))
                    print(f"Original access: {data.get('access')}")
                    
                    # FORCE ALLOW
                    data["access"] = "allow"
                    
                    # Add stream URLs if missing
                    if "streamUrl" not in data:
                        content_id = data.get("id", "")
                        data["streamUrl"] = f"https://stream.toffeelive.com/{content_id}/playlist.m3u8"
                        data["manifestUrl"] = f"https://manifest.toffeelive.com/{content_id}/manifest.m3u8"
                    
                    print(f"Modified to: allow")
                    
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
        
        # =================================================
        # OPEN CONTENT PAGE
        # =================================================
        
        print(f"\n[OPENING] {CONTENT_URL}")
        
        await page.goto(
            CONTENT_URL,
            wait_until="networkidle",
            timeout=60000
        )
        
        print(f"Page title: {await page.title()}")
        
        # Wait for player
        await page.wait_for_timeout(10000)
        
        # =================================================
        # EXTRACT STREAM DATA
        # =================================================
        
        print("\n" + "=" * 60)
        print("EXTRACTING STREAM DATA")
        print("=" * 60)
        
        # Get from video elements
        videos = await page.query_selector_all("video")
        print(f"Video elements: {len(videos)}")
        
        stream_urls = []
        
        for i, video in enumerate(videos):
            src = await video.get_attribute("src")
            if src:
                print(f"  Video {i}: {src}")
                stream_urls.append(src)
        
        # Get from window objects
        js_data = await page.evaluate("""
            () => {
                const result = {};
                
                // Check common player variables
                ['player', 'videoPlayer', 'hls', 'dash', 'streamData'].forEach(key => {
                    if (window[key]) {
                        try {
                            result[key] = JSON.parse(JSON.stringify(window[key]));
                        } catch(e) {
                            result[key] = String(window[key]);
                        }
                    }
                });
                
                // Get video src
                const v = document.querySelector('video');
                if (v) {
                    result.videoSrc = v.src;
                    result.videoCurrentSrc = v.currentSrc;
                }
                
                return result;
            }
        """)
        
        print(f"\nPlayer data keys: {list(js_data.keys())}")
        
        # Get network performance entries
        perf_entries = await page.evaluate("""
            () => performance.getEntriesByType('resource')
                .filter(r => r.name.includes('.m3u8') || r.name.includes('.mp4'))
                .map(r => r.name)
        """)
        
        print(f"\nNetwork media URLs: {len(perf_entries)}")
        for url in perf_entries[:5]:
            print(f"  - {url}")
        
        # =================================================
        # SAVE RESULTS
        # =================================================
        
        results = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "content_url": CONTENT_URL,
            "auth_used": True,
            "video_elements": len(videos),
            "stream_urls": stream_urls,
            "player_data": js_data,
            "network_urls": perf_entries
        }
        
        with open(f"{OUTPUT_DIR}/stream_data.json", "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n✓ Data saved to {OUTPUT_DIR}/stream_data.json")
        
        await browser.close()


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())
