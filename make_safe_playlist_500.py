from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry
import threading

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
TARGET_USER_AGENT = "Denver1760"  # Exact working user-agent
REGULAR_CHANNELS_LIMIT = 1000  # Exactly 1000 regular channels (excluding priority ones)
MAX_WORKERS = 60     # Safe workers balance for speed & reliability

# Priority channels to place at the very top (Excluded from the 1000 regular count)
PRIORITY_KEYWORDS = [
    "nick", 
    "star sports", 
    "ptc music", 
    "disney"
]

counter_lock = threading.Lock()
processed_count = 0

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
        # 1. Extract and follow redirects for License Key URL
        key_url = None
        for b in range(max(0, i - 3), i):
            sub_b = lines[b].strip()
            if "inputstream.adaptive.license_key=" in sub_b:
                key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

        resolved_key_data = None
        if key_url:
            try:
                if '"' in key_url:
                    key_url = key_url.replace('"', "")
                k_res = session.get(key_url, headers={"User-Agent": TARGET_USER_AGENT}, allow_redirects=True, timeout=3)
                if k_res.status_code == 200:
                    try:
                        key_json = k_res.json()
                        resolved_key_data = json.dumps(key_json)
                    except Exception:
                        resolved_key_data = k_res.url
                else:
                    resolved_key_data = key_url
            except Exception:
                resolved_key_data = key_url

        channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
        
        if resolved_key_data:
            channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={resolved_key_data}")

        channel_lines.append(f"#EXTVLCOPT:http-user-agent={TARGET_USER_AGENT}")

        # 2. Extract MPD line and follow redirects to reach the ultimate real stream URL
        mpd_line = None
        for f in range(i + 1, min(len(lines), i + 4)):
            sub_f = lines[f].strip()
            if sub_f.startswith("http") and ".mpd" in sub_f:
                mpd_line = sub_f

        url_added = False
        if mpd_line:
            try:
                channel_headers = {"User-Agent": TARGET_USER_AGENT}
                r = session.get(mpd_line, headers=channel_headers, allow_redirects=True, timeout=3)
                
                real_url = r.url if r.status_code == 200 else mpd_line
                clean_url = real_url.strip().split()[0]
                if clean_url.endswith("~"):
                    clean_url = clean_url[:-1]
                
                # Check for embedded cookies in the final URL and format properly
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

def generate_priority_playlist():
    global processed_count
    processed_count = 0
    print(f"[*] Downloading playlist and filtering priority channels + exactly {REGULAR_CHANNELS_LIMIT} regular channels...")
    session = get_robust_session()
    try:
        res = session.get(PLAYLIST_URL, headers={"User-Agent": TARGET_USER_AGENT})
        if res.status_code != 200:
            print("[-] Failed to fetch playlist.")
            return

        lines = res.text.splitlines()  

        all_extinf_indices = []
        for i, line in enumerate(lines):
            if line.strip().startswith("#EXTINF"):
                all_extinf_indices.append(i)

        if not all_extinf_indices:
            print("[-] No channels found in playlist.")
            return

        priority_indices = []
        regular_indices = []

        for idx in all_extinf_indices:
            channel_title = lines[idx].lower()
            is_priority = False
            for kw in PRIORITY_KEYWORDS:
                if kw in channel_title:
                    is_priority = True
                    break
            
            if is_priority:
                priority_indices.append(idx)
            else:
                regular_indices.append(idx)

        # Separate selection: Priority channels + up to 1000 regular channels (avoiding duplicates if priority is also in regular)
        priority_set = set(priority_indices)
        filtered_regular_indices = [idx for idx in regular_indices if idx not in priority_set]
        
        # Take up to REGULAR_CHANNELS_LIMIT from regular channels
        selected_regular = filtered_regular_indices[:REGULAR_CHANNELS_LIMIT]

        # Combine: Priority first, then the 1000 regular channels
        target_indices = priority_indices + selected_regular

        print(f"[*] Found {len(priority_indices)} priority channels.")
        print(f"[*] Added {len(selected_regular)} regular channels (Limit: {REGULAR_CHANNELS_LIMIT}).")
        print(f"[*] Total channels to process: {len(target_indices)}.\n")
        print(f"[*] Launching multithreading...\n")

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

        new_lines = ["#EXTM3U"]
        for idx in target_indices:
            if idx in channel_results:
                new_lines.extend(channel_results[idx])
            else:
                new_lines.append(lines[idx].strip())
                new_lines.append("http://dummy-link-to-prevent-break")

        output_file = "safe_500_channels.m3u"  
        with open(output_file, "w", encoding="utf-8") as f:  
            f.write("\n".join(new_lines))  

        print(f"\n\n[+] Success! Playlist saved as '{output_file}' with priority channels + {len(selected_regular)} regular channels.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_priority_playlist()
                
