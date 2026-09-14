from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://game.playindia.fun/",
    "Origin": "https://game.playindia.fun"
}

MAX_CHANNELS = 500  
MAX_WORKERS = 100    

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    
    adapter = HTTPAdapter(
        pool_maxsize=MAX_WORKERS, 
        pool_block=False, 
        max_retries=retries
    )
    
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

session = get_robust_session()

def process_channel_block(channel_data):
    i, lines = channel_data
    line = lines[i].strip()
    extinf_line = line

    key_url = None
    for b in range(max(0, i - 3), i):
        sub_b = lines[b].strip()
        if "inputstream.adaptive.license_key=" in sub_b:
            key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

    user_agent = "plattv/7.1.5"
    stream_line = None
    
    for f in range(i + 1, min(len(lines), i + 4)):
        sub_f = lines[f].strip()
        if sub_f.startswith("#EXTVLCOPT:http-user-agent="):
            user_agent = sub_f.split("=")[1].strip()
        if sub_f.startswith("http") and not sub_f.startswith("#"):
            stream_line = sub_f

    embedded_key_data = None
    if key_url:
        try:
            if '"' in key_url:
                key_url = key_url.replace('"', "")
            key_res = session.get(key_url, headers=HEADERS)
            if key_res.status_code == 200:
                key_json = key_res.json()
                embedded_key_data = json.dumps(key_json)
        except Exception:
            pass

    channel_lines = []
    
    # Working format order: #EXTINF pehlan aavega
    channel_lines.append(extinf_line)
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

    if stream_line:
        try:
            channel_headers = {
                "User-Agent": user_agent,
                "Referer": "https://game.playindia.fun/",
                "Origin": "https://game.playindia.fun"
            }
            r = session.get(
                stream_line, headers=channel_headers, allow_redirects=False
            )

            real_url = (  
                r.headers.get("Location")  
                if r.status_code in [301, 302, 303, 307, 308]  
                else stream_line  
            )  
            clean_url = real_url.strip().split()[0]  
            if clean_url.endswith("~"):  
                clean_url = clean_url[:-1]  
            
            # Working format vangu cookie nu #EXTHTTP format vich convert karna
            if "%7Ccookie=" in clean_url:
                parts = clean_url.split("%7Ccookie=")
                base_url = parts[0]
                cookie_val = parts[1].split("&")[0] if "&" in parts[1] else parts[1]
                channel_lines.append(f'#EXTHTTP:{{"cookie":"{cookie_val}"}}')
                channel_lines.append(base_url)
            elif "|cookie=" in clean_url:
                parts = clean_url.split("|cookie=")
                base_url = parts[0]
                cookie_val = parts[1].split("&")[0] if "&" in parts[1] else parts[1]
                channel_lines.append(f'#EXTHTTP:{{"cookie":"{cookie_val}"}}')
                channel_lines.append(base_url)
            else:
                channel_lines.append(clean_url)
                
        except Exception:  
            clean_url = stream_line.strip().split()[0]  
            if clean_url.endswith("~"):  
                clean_url = clean_url[:-1]  
            channel_lines.append(clean_url)

    return i, channel_lines

def generate_safe_playlist_500():
    print(
        f"[*] Downloading target playlist and extracting keys for up to"
        f" {MAX_CHANNELS} channels..."
    )
    try:
        res = session.get(PLAYLIST_URL, headers=HEADERS)
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

        print(  
            f"[*] Found {len(target_indices)} channels. Launching with"  
            f" {MAX_WORKERS} max workers..."  
        )  

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

        print(  
            f"\n[+] Success! Exactly {len(channel_results)} channels saved as"  
            f" '{output_file}'."  
        )

    except Exception as e:
        print(f"[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_500()
            
