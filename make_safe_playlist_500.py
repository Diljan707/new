from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry
import threading

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
HEADERS = {"User-Agent": "plattv/7.1.5"}
MAX_CHANNELS = 1000  # Exact 1000 channels limit from source
MAX_WORKERS = 60     # Safe workers balance for speed & reliability

counter_lock = threading.Lock()
processed_count = 0

# --- CUSTOM ADDITIONAL CHANNELS (Placed at the very beginning) ---
# You can add as many as you want here. They will NOT count towards your 1000 limit.
CUSTOM_CHANNELS = [
    """#EXTINF:-1 tvg-id="Nick.in" tvg-name="Nick" tvg-logo="https://i.imgur.com/nick.png" group-title="Kids",Nick
#KODIPROP:inputstream.adaptive.license_type=clearkey
#KODIPROP:inputstream.adaptive.license_key={"keys":[{"kty":"oct","k":"","kid":""}]}
#EXTVLCOPT:http-user-agent=plattv/7.1.5
http://your-nick-stream-link-here.mpd""",

    """#EXTINF:-1 tvg-id="StarPlus.in" tvg-name="Star Plus" tvg-logo="https://i.imgur.com/starplus.png" group-title="Entertainment",Star Plus
#KODIPROP:inputstream.adaptive.license_type=clearkey
#KODIPROP:inputstream.adaptive.license_key={"keys":[{"kty":"oct","k":"","kid":""}]}
#EXTVLCOPT:http-user-agent=plattv/7.1.5
http://your-star-stream-link-here.mpd""",

    """#EXTINF:-1 tvg-id="Disney.in" tvg-name="Disney" tvg-logo="https://i.imgur.com/disney.png" group-title="Kids",Disney
#KODIPROP:inputstream.adaptive.license_type=clearkey
#KODIPROP:inputstream.adaptive.license_key={"keys":[{"kty":"oct","k":"","kid":""}]}
#EXTVLCOPT:http-user-agent=plattv/7.1.5
http://your-disney-stream-link-here.mpd""",

    """#EXTINF:-1 tvg-id="PTCPunjabi.in" tvg-name="PTC Punjabi" tvg-logo="https://i.imgur.com/ptc.png" group-title="Punjabi",PTC Punjabi
#KODIPROP:inputstream.adaptive.license_type=clearkey
#KODIPROP:inputstream.adaptive.license_key={"keys":[{"kty":"oct","k":"","kid":""}]}
#EXTVLCOPT:http-user-agent=plattv/7.1.5
http://your-ptc-stream-link-here.mpd"""
]

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

def process_single_channel(i, lines, session):
    line = lines[i].strip()
    extinf_line = line

    raw_stream_line = ""
    for f in range(i + 1, min(len(lines), i + 5)):
        if lines[f].strip().startswith("http"):
            raw_stream_line = lines[f].strip().split()[0]
            if raw_stream_line.endswith("~"):
                raw_stream_line = raw_stream_line[:-1]
            break

    channel_lines = [extinf_line]

    try:
        key_url = None
        for b in range(max(0, i - 3), i):
            sub_b = lines[b].strip()
            if "inputstream.adaptive.license_key=" in sub_b:
                key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

        user_agent = "plattv/7.1.5"
        mpd_line = None
        for f in range(i + 1, min(len(lines), i + 4)):
            sub_f = lines[f].strip()
            if sub_f.startswith("#EXTVLCOPT:http-user-agent="):
                user_agent = sub_f.split("=")[1].strip()
            if sub_f.startswith("http") and ".mpd" in sub_f:
                mpd_line = sub_f

        embedded_key_data = None
        if key_url:
            try:
                if '"' in key_url:
                    key_url = key_url.replace('"', "")
                key_res = session.get(key_url, headers={"User-Agent": user_agent}, timeout=3)
                if key_res.status_code == 200:
                    key_json = key_res.json()
                    embedded_key_data = json.dumps(key_json)
            except Exception:
                pass

        channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
        
        if embedded_key_data:
            channel_lines.append(
                f"#KODIPROP:inputstream.adaptive.license_key={embedded_key_data}"
            )
        elif key_url:
            channel_lines.append(
                f"#KODIPROP:inputstream.adaptive.license_key={key_url}"
            )

        channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")

        url_added = False
        if mpd_line:
            try:
                channel_headers = {"User-Agent": user_agent}
                r = session.get(
                    mpd_line, headers=channel_headers, allow_redirects=False, timeout=3
                )

                if r.status_code == 403 and raw_stream_line:
                    channel_lines.append(raw_stream_line)
                    url_added = True
                else:
                    real_url = (  
                        r.headers.get("Location")  
                        if r.status_code in [301, 302, 303, 307, 308]  
                        else mpd_line  
                    )  
                    clean_url = real_url.strip().split()[0]  
                    if clean_url.endswith("~"):  
                        clean_url = clean_url[:-1]  
                    
                    if "__hdnea__=" in clean_url:
                        try:
                            parts = clean_url.split("__hdnea__=")
                            if len(parts) > 1:
                                hdnea_val = parts[1].split("&")[0]
                                channel_lines.append(f'#EXTHTTP:{{"cookie":"__hdnea__={hdnea_val}"}}')
                        except Exception:
                            pass
                        channel_lines.append(clean_url)
                        url_added = True
                    elif "%7Ccookie=" in clean_url:
                        parts = clean_url.split("%7Ccookie=")
                        base_url = parts[0]
                        cookie_val = parts[1].split("&")[0] if "&" in parts[1] else parts[1]
                        channel_lines.append(f'#EXTHTTP:{{"cookie":"{cookie_val}"}}')
                        channel_lines.append(base_url)
                        url_added = True
                    elif "|cookie=" in clean_url:
                        parts = clean_url.split("|cookie=")
                        base_url = parts[0]
                        cookie_val = parts[1].split("&")[0] if "&" in parts[1] else parts[1]
                        channel_lines.append(f'#EXTHTTP:{{"cookie":"{cookie_val}"}}')
                        channel_lines.append(base_url)
                        url_added = True
                    else:
                        channel_lines.append(clean_url)
                        url_added = True
            except Exception:
                pass

        if not url_added and raw_stream_line:
            channel_lines.append(raw_stream_line)
        elif not url_added and not raw_stream_line:
            channel_lines.append("http://dummy-link-to-prevent-break")

    except Exception:
        if raw_stream_line:
            channel_lines.append(raw_stream_line)
        else:
            channel_lines.append("http://dummy-link-to-prevent-break")

    return channel_lines

def generate_safe_playlist_1000():
    global processed_count
    processed_count = 0
    print(f"[*] Downloading playlist and processing up to {MAX_CHANNELS} channels using {MAX_WORKERS} workers...")
    session = get_robust_session()
    try:
        res = session.get(PLAYLIST_URL, headers={"User-Agent": "plattv/7.1.5"})
        if res.status_code != 200:
            print("[-] Failed to fetch playlist.")
            return

        lines = res.text.splitlines()  

        target_indices = []  
        for i, line in enumerate(lines):  
            if line.strip().startswith("#EXTINF"):  
                target_indices.append(i)  
                if len(target_indices) >= MAX_CHANNELS:  
                    break  

        if not target_indices:  
            print("[-] No channels found in playlist.")  
            return  

        print(f"[*] Found {len(target_indices)} channels from source. Adding custom channels at top...")  

        channel_results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(process_single_channel, idx, lines, session): idx
                for idx in target_indices
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    channel_lines = future.result()
                    channel_results[idx] = channel_lines
                except Exception:
                    fallback_lines = [lines[idx].strip()]
                    raw_url = ""
                    for f in range(idx + 1, min(len(lines), idx + 5)):
                        if lines[f].strip().startswith("http"):
                            raw_url = lines[f].strip().split()[0]
                            if raw_url.endswith("~"):
                                raw_url = raw_url[:-1]
                            break
                    if raw_url:
                        fallback_lines.append(raw_url)
                    else:
                        fallback_lines.append("http://dummy-link-to-prevent-break")
                    channel_results[idx] = fallback_lines

                with counter_lock:
                    processed_count += 1
                    print(f"[*] Progress: {processed_count}/{len(target_indices)} channels processed...", end="\r")

        # Build final playlist starting with #EXTM3U, then custom channels, then the 1000 fetched channels
        new_lines = ["#EXTM3U"]
        
        # Inject custom channels first
        for custom_ch in CUSTOM_CHANNELS:
            new_lines.extend(custom_ch.strip().splitlines())

        # Inject fetched channels next
        for idx in target_indices:
            if idx in channel_results:
                new_lines.extend(channel_results[idx])
            else:
                new_lines.append(lines[idx].strip())
                new_lines.append("http://dummy-link-to-prevent-break")

        output_file = "safe_500_channels.m3u"  
        with open(output_file, "w", encoding="utf-8") as f:  
            f.write("\n".join(new_lines))  

        total_saved = len(target_indices) + len(CUSTOM_CHANNELS)
        print(f"\n\n[+] Success! Total {total_saved} channels saved (1000 from link + {len(CUSTOM_CHANNELS)} custom channels) in '{output_file}'.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_1000()
