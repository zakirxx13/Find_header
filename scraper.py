#!/usr/bin/env python3
"""
ToffeeLive Scraper - Extracts channel IDs and generates M3U8 playlist
"""

import json
import re
import os
import requests
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin, parse_qs, urlparse


class ToffeeScraper:
    def __init__(self):
        self.base_url = "https://toffeelive.com"
        self.api_url = os.getenv("API_BASE_URL", "https://entitlement-prod.services.toffeelive.com/toffee/BD/DK/web/playback")
        self.channels = []
        
        # Target collection URLs
        self.collections = [
            "https://toffeelive.com/en/live",
            "https://toffeelive.com/en/collections/58bd377f146fcd2436f0b258eebf43c1",
            "https://toffeelive.com/en/collections/5024eb274066fe74ee0b3d0239aa2fbc",
            "https://toffeelive.com/en/collections/3adc241ef7c7788fb724d83a2c7cc3a5"
        ]

    def extract_channel_id_from_url(self, url):
        """Extract channel ID from watch page URL"""
        patterns = [
            r'/watch/([a-f0-9]+)',
            r'channel[_-]?id[=:]([a-f0-9]+)',
            r'id[=:]([a-f0-9]{24,})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def get_channel_id_from_page(self, page, watch_url):
        """Navigate to watch page and extract channel ID from API calls or page data"""
        try:
            # Listen for API calls
            channel_id = None
            
            def handle_route(route, request):
                nonlocal channel_id
                if "playback" in request.url or "entitlement" in request.url:
                    # Extract from request URL or body
                    post_data = request.post_data
                    if post_data:
                        try:
                            data = json.loads(post_data)
                            if 'id' in data:
                                channel_id = data['id']
                        except:
                            pass
                route.continue_()

            page.route("**/*", handle_route)
            
            # Navigate to watch page
            page.goto(watch_url, wait_until="networkidle")
            
            # Try to get from page content
            if not channel_id:
                # Look for channel ID in script tags or data attributes
                scripts = page.query_selector_all('script')
                for script in scripts:
                    content = script.inner_text()
                    # Look for channel ID patterns
                    matches = re.findall(r'"id"\s*:\s*"([a-f0-9]{24,})"', content)
                    if matches:
                        channel_id = matches[0]
                        break
            
            # Try from URL
            if not channel_id:
                channel_id = self.extract_channel_id_from_url(page.url)
            
            # Try from meta or data attributes
            if not channel_id:
                meta = page.query_selector('meta[name="channel-id"]')
                if meta:
                    channel_id = meta.get_attribute('content')
            
            return channel_id
            
        except Exception as e:
            print(f"Error extracting from {watch_url}: {e}")
            return None

    def scrape_collection(self, page, collection_url):
        """Scrape all channel links from a collection page"""
        channels = []
        
        try:
            page.goto(collection_url, wait_until="networkidle")
            
            # Wait for content to load
            page.wait_for_load_state("domcontentloaded")
            
            # Extract all watch page links
            links = page.query_selector_all('a[href*="/watch/"]')
            
            for link in links:
                href = link.get_attribute('href')
                if href:
                    full_url = urljoin(self.base_url, href)
                    # Get channel name from link text or alt
                    name_elem = link.query_selector('img') or link
                    channel_name = name_elem.get_attribute('alt') or \
                                 name_elem.inner_text().strip() or \
                                 "Unknown Channel"
                    
                    channels.append({
                        'name': channel_name,
                        'watch_url': full_url
                    })
            
            # Also look for channel cards with data attributes
            cards = page.query_selector_all('[data-channel-id], .channel-card, .live-item')
            for card in cards:
                channel_id = card.get_attribute('data-channel-id')
                if channel_id:
                    name_elem = card.query_selector('.channel-name, .title, h3, h4')
                    channel_name = name_elem.inner_text().strip() if name_elem else "Unknown"
                    channels.append({
                        'name': channel_name,
                        'channel_id': channel_id
                    })
                    
        except Exception as e:
            print(f"Error scraping collection {collection_url}: {e}")
            
        return channels

    def call_api(self, channel_id):
        """Call the entitlement API to get stream URL"""
        try:
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Origin': 'https://toffeelive.com',
                'Referer': 'https://toffeelive.com/',
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.0'
            }
            
            payload = {
                'id': channel_id,
                'platform': 'web',
                'region': 'BD'
            }
            
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                # Extract M3U8 URL from response
                if 'url' in data:
                    return data['url']
                elif 'data' in data and 'url' in data['data']:
                    return data['data']['url']
                elif 'playback' in data:
                    return data['playback']
                    
            print(f"API Error for {channel_id}: {response.status_code}")
            return None
            
        except Exception as e:
            print(f"API call failed for {channel_id}: {e}")
            return None

    def generate_m3u8(self, channels_with_streams):
        """Generate M3U8 playlist file"""
        m3u8_content = ["#EXTM3U", "#EXT-X-VERSION:3"]
        
        for ch in channels_with_streams:
            if ch.get('stream_url'):
                # Clean channel name for display
                name = ch['name'].replace(',', ' ').strip()
                group = ch.get('group', 'Toffee Live')
                
                m3u8_content.append(f'#EXTINF:-1 tvg-name="{name}" group-title="{group}",{name}')
                m3u8_content.append(ch['stream_url'])
        
        return '\n'.join(m3u8_content)

    def run(self):
        """Main execution"""
        print("Starting ToffeeLive scraper...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.0'
            )
            
            page = context.new_page()
            
            all_channels = []
            
            # Scrape all collections
            for collection_url in self.collections:
                print(f"Scraping: {collection_url}")
                channels = self.scrape_collection(page, collection_url)
                all_channels.extend(channels)
                print(f"Found {len(channels)} channels")
            
            # Remove duplicates
            seen = set()
            unique_channels = []
            for ch in all_channels:
                key = ch.get('watch_url') or ch.get('channel_id')
                if key and key not in seen:
                    seen.add(key)
                    unique_channels.append(ch)
            
            print(f"\nTotal unique channels: {len(unique_channels)}")
            
            # Extract channel IDs and get stream URLs
            channels_with_streams = []
            
            for ch in unique_channels:
                print(f"Processing: {ch['name']}")
                
                # Get channel ID if not already have
                channel_id = ch.get('channel_id')
                if not channel_id and ch.get('watch_url'):
                    channel_id = self.get_channel_id_from_page(page, ch['watch_url'])
                
                if channel_id:
                    ch['channel_id'] = channel_id
                    # Call API to get stream URL
                    stream_url = self.call_api(channel_id)
                    if stream_url:
                        ch['stream_url'] = stream_url
                        channels_with_streams.append(ch)
                        print(f"  ✓ Got stream URL")
                    else:
                        print(f"  ✗ No stream URL")
                else:
                    print(f"  ✗ No channel ID found")
            
            browser.close()
        
        # Save results
        with open('channels.json', 'w', encoding='utf-8') as f:
            json.dump(channels_with_streams, f, indent=2, ensure_ascii=False)
        
        # Generate M3U8
        m3u8_content = self.generate_m3u8(channels_with_streams)
        with open('playlist.m3u8', 'w', encoding='utf-8') as f:
            f.write(m3u8_content)
        
        print(f"\n✅ Scraping complete!")
        print(f"   Channels with streams: {len(channels_with_streams)}")
        print(f"   Saved: channels.json, playlist.m3u8")


if __name__ == "__main__":
    scraper = ToffeeScraper()
    scraper.run()
