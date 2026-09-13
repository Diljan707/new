from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
HEADERS = {"User-Agent": "Denver1769"}

# Advanced settings for maximum speed and zero latency
MAX_CHANNELS = 600
MAX_WORKERS = 100

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

session = get_robust_session()

def process_channel_block(channel_data):
    """Advanced processing: Robust kid:key extraction + MPD redirection + High speed."""
    i, lines = channel_data
    line = lines[i].strip()
    extinf_line = line

    key_url = None
    for b in range(max(0, i - 3), i):
        sub_b = lines[b].strip()
        if "inputstream.adaptive.license_key=" in sub_b:
            key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

    user_agent = "Denver1769"
    mpd_line = None
    for f in range(i + 1, min(len(lines), i + 4)):
        sub_f = lines[f].strip()
        if sub_f.startswith("#EXTVLCOPT:http-user-agent="):
            user_agent = sub_f.split("=")[1].strip()
        if sub_f.startswith("http") and ".mpd" in sub_f:
            mpd_line = sub_f

    clearkey_string = None
    if key_url:
        try:
            if '"' in key_url:
                key_url = key_url.replace('"', "")
            key_res = session.get(key_url, headers=HEADERS, timeout=3)
            if key_res.status_code == 200:
                key_json = key_res.json()
                
                # Robust extraction for various JSON structures
                keys_list = []
                if isinstance(key_json, dict):
                    keys_list = key_json.get("keys", [])
                elif isinstance(key_json, list):
                    keys_list = key_json
                
                pairs = []
                for k in keys_list:
                    if isinstance(k, dict):
                        kid = k.get('kid')
                        key = k.get('key')
                        if kid and key:
                            pairs.append(f"{kid}:{key}")
                
                if pairs:
                    clearkey_string = ",".join(pairs)
        except Exception:
            pass

    channel_lines = []
    channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
    
    if clearkey_string:
        # Direct kid:key format pass hoga (No JSON parsing delay in player)
        channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={clearkey_string}")
    elif key_url:
        channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={key_url}")

    channel_lines.append(extinf_line)
    channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")

    if mpd_line:
        try:
            channel_headers = {"User-Agent": user_agent}
            r = session.get(mpd_line, headers=channel_headers, allow_redirects=False, timeout=3)
            real_url = (  
                r.headers.get("Location")  
                if r.status_code in [301, 302, 303, 307, 308]  
                else mpd_line  
            )  
            clean_url = real_url.strip().split()[0]  
            if clean_url.endswith("~"):  
                clean_url = clean_url[:-1]  
            channel_lines.append(clean_url)  
        except Exception:  
            clean_url = mpd_line.strip().split()[0]  
            if clean_url.endswith("~"):  
                clean_url = clean_url[:-1]  
            channel_lines.append(clean_url)

    return i, channel_lines

def generate_safe_playlist_500():
    print(f"[*] Downloading playlist for advanced processing ({MAX_CHANNELS} channels)...")
    try:
        res = session.get(PLAYLIST_URL, headers=HEADERS, timeout=10)
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

        print(f"[*] Processing with {MAX_WORKERS} workers (Advanced Kid:Key + Redirect mode)...")  

        channel_results = {}  
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:  
            futures = {  
                executor.submit(process_channel_block, (idx, lines)): idx  
                for idx in target_indices  
            }  
            for future in as_completed(futures):  
                try:  
                    idx, channel_lines = future.result()  
                    channel_results[idx] = channel_lines  
                except Exception as e:  
                    print(f"[-] Error processing a channel: {e}")  

        new_lines = ["#EXTM3U"]  
        for idx in target_indices:  
            if idx in channel_results:  
                new_lines.extend(channel_results[idx])  

        output_file = "safe_500_channels.m3u"  
        with open(output_file, "w", encoding="utf-8") as f:  
            f.write("\n".join(new_lines))  

        print(f"\n[+] Success! Advanced optimized playlist saved as '{output_file}'.")

    except Exception as e:
        print(f"[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_500()
            
