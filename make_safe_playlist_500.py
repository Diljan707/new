from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry
import threading

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
MAX_CHANNELS = 800   # Exact 800 channels limit
MAX_WORKERS = 60     # Super fast processing workers
DEFAULT_USER_AGENT = "plaYtv/7.1.5"

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
        key_url = None
        for b in range(max(0, i - 3), i):
            sub_b = lines[b].strip()
            if "inputstream.adaptive.license_key=" in sub_b:
                key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

        user_agent = DEFAULT_USER_AGENT
        mpd_line = None
        for f in range(i + 1, min(len(lines), i + 4)):
            sub_f = lines[f].strip()
            if sub_f.startswith("#EXTVLCOPT:http-user-agent="):
                user_agent = sub_f.split("=")[1].strip()
            if sub_f.startswith("http") and ".mpd" in sub_f:
                mpd_line = sub_f

        direct_clearkey = None
        if key_url:
            try:
                if '"' in key_url:
                    key_url = key_url.replace('"', "")
                
                key_headers = {
                    "User-Agent": user_agent,
                    "Referer": "https://www.jiotv.com/",
                    "Accept": "application/json, text/javascript, */*; q=0.01"
                }
                key_res = session.get(key_url, headers=key_headers, timeout=3)
                if key_res.status_code == 200:
                    key_json = key_res.json()
                    raw_keys = []
                    if "base64" in key_json and "keys" in key_json["base64"]:
                        raw_keys = key_json["base64"]["keys"]
                    elif "keys" in key_json:
                        raw_keys = key_json["keys"]
                    
                    if raw_keys:
                        pair_list = []
                        seen_kids = set()
                        for k in raw_keys:
                            if "kid" in k and "k" in k:
                                kid_val = k.get("kid")
                                k_val = k.get("k")
                                if kid_val not in seen_kids:
                                    seen_kids.add(kid_val)
                                    pair_list.append(f"{kid_val}:{k_val}")
                        
                        if pair_list:
                            direct_clearkey = ",".join(pair_list)
            except Exception:
                pass

        channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
        
        if direct_clearkey:
            channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={direct_clearkey}")
        elif key_url:
            channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={key_url}")

        channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")
        channel_lines.append('#EXTHTTP:{"Origin":"https://www.jiotv.com/","Referer":"https://www.jiotv.com/"}')

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
        res = session.get(PLAYLIST_URL, headers={"User-Agent": DEFAULT_USER_AGENT})
        if res.status_code != 200:
            print("[-] Failed to fetch playlist.")
            return

        lines = res.text.splitlines()  

        star_keyword = "star"
        other_keywords = ("nick", "disney", "ptc", "zee", "sony")

        star_indices = []
        other_priority_indices = []
        regular_indices = []

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
                    channel_results[idx] = future.result()
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
            channel_listed = channel_results.get(idx)
            if channel_listed:
                new_lines.extend(channel_listed)
            else:
                new_lines.append(lines[idx].strip())
                new_lines.append("http://dummy-link-to-prevent-break")

        output_file = "safe_500_channels.m3u"  
        with open(output_file, "w", encoding="utf-8") as f:  
            f.write("\n".join(new_lines))  

        print(f"\n\n[+] Success! Playlist saved as '{output_file}' with original stable separate key pairs format.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_1000()
