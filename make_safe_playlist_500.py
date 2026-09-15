from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import json
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry
import threading

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
HEADERS = {"User-Agent": "plattv/7.1.5"}
MAX_CHANNELS = 800   # Exact 800 channels limit
MAX_WORKERS = 60     # Safe workers balance for speed & reliability

counter_lock = threading.Lock()
processed_count = 0

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

def b64url_to_hex(val):
    try:
        b64 = val.replace("-", "+").replace("_", "/")
        b64 += "=" * ((4 - len(b64) % 4) % 4)
        return base64.b64decode(b64).hex()
    except Exception:
        return val

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

        formatted_key_str = None
        if key_url:
            try:
                if '"' in key_url:
                    key_url = key_url.replace('"', "")
                key_res = session.get(key_url, headers={"User-Agent": user_agent}, timeout=3)
                if key_res.status_code == 200:
                    key_json = key_res.json()
                    keys_list = key_json.get("keys", [])
                    key_pairs = []
                    for k_item in keys_list:
                        kid = k_item.get("kid")
                        k = k_item.get("k")
                        if kid and k:
                            # Convert to hex if base64url, format as key:key_id (k:kid)
                            k_hex = b64url_to_hex(k)
                            kid_hex = b64url_to_hex(kid)
                            key_pairs.append(f"{k_hex}:{kid_hex}")
                    if key_pairs:
                        formatted_key_str = ",".join(key_pairs)
            except Exception:
                pass

        channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
        
        if formatted_key_str:
            channel_lines.append(
                f"#KODIPROP:inputstream.adaptive.license_key={formatted_key_str}"
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
    print(f"[*] Downloading playlist and processing channels using {MAX_WORKERS} workers...")
    session = get_robust_session()
    try:
        res = session.get(PLAYLIST_URL, headers={"User-Agent": "plattv/7.1.5"})
        if res.status_code != 200:
            print("[-] Failed to fetch playlist.")
            return

        lines = res.text.splitlines()  

        star_keyword = "star"
        other_keywords = ("nick", "disney", "ptc", "zee", "sony")

        star_indices = []
        other_priority_indices = []
        regular_indices = []

        # First pass: Categorize lines into Star first, then other priorities, then regular channels up to 800 limit
        for i, line in enumerate(lines):  
            if line.strip().startswith("#EXTINF"):  
                channel_name = line.split(",")[-1].strip().lower()
                
                if star_keyword in channel_name:
                    if i not in star_indices:
                        star_indices.append(i)
                elif any(kw in channel_name for kw in other_keywords):
                    if i not in other_priority_indices:
                        other_priority_indices.append(i)
                else:
                    if len(regular_indices) < MAX_CHANNELS:
                        regular_indices.append(i)

        target_indices = star_indices + other_priority_indices + regular_indices
        
        if not target_indices:  
            print("[-] No channels found in playlist.")  
            return  

        print(f"[*] Found {len(star_indices)} Star channels, {len(other_priority_indices)} other priority channels, and {len(regular_indices)} regular channels. Processing...")  

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

        # Build final playlist starting with #EXTM3U
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

        print(f"\n\n[+] Success! Playlist saved as '{output_file}' with key:key_id format applied.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_1000()
        
