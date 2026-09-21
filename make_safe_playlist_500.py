from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import base64
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry
import threading

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
MAX_CHANNELS = 1000  # Exact 1000 channels limit
MAX_WORKERS = 60     # Safe workers balance for speed & reliability

counter_lock = threading.Lock()
processed_count = 0

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

def b64_to_hex(b64_str):
    # Base64 string nu hex vich convert karn di function
    padding = 4 - (len(b64_str) % 4)
    if padding < 4:
        b64_str += '=' * padding
    try:
        decoded = base64.urlsafe_b64decode(b64_str)
        return decoded.hex()
    except Exception:
        return b64_str

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

        user_agent = "plaYtv/7.1.5"
        mpd_line = None
        for f in range(i + 1, min(len(lines), i + 4)):
            sub_f = lines[f].strip()
            if sub_f.startswith("#EXTVLCOPT:http-user-agent="):
                user_agent = sub_f.split("=")[1].strip()
            if sub_f.startswith("http") and ".mpd" in sub_f:
                mpd_line = sub_f

        formatted_license_key = None
        if key_url:
            try:
                if '"' in key_url:
                    key_url = key_url.replace('"', "")
                key_res = session.get(key_url, headers={"User-Agent": user_agent}, timeout=3)
                if key_res.status_code == 200:
                    key_json = key_res.json()
                    
                    # Extract keys and convert base64 kid/k to hex format (kid:k)
                    key_pairs = []
                    keys_list = key_json.get("base64", {}).get("keys", [])
                    for k_obj in keys_list:
                        kid_b64 = k_obj.get("kid", "")
                        k_b64 = k_obj.get("k", "")
                        if kid_b64 and k_b64:
                            kid_hex = b64_to_hex(kid_b64)
                            k_hex = b64_to_hex(k_b64)
                            key_pairs.append(f"{kid_hex}:{k_hex}")
                    
                    if key_pairs:
                        formatted_license_key = ",".join(key_pairs)
            except Exception:
                pass

        channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
        
        if formatted_license_key:
            channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={formatted_license_key}")
        elif key_url:
            channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={key_url}")

        channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")

        url_added = False
        cookie_val = None

        if mpd_line:
            try:
                channel_headers = {"User-Agent": user_agent}
                r = session.get(
                    mpd_line, headers=channel_headers, allow_redirects=False, timeout=3
                )

                if r.status_code == 403 and raw_stream_line:
                    clean_url = raw_stream_line
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
                                cookie_val = f"__hdnea__={parts[1].split('&')[0]}"
                        except Exception:
                            pass
                    elif "%7Ccookie=" in clean_url:
                        parts = clean_url.split("%7Ccookie=")
                        clean_url = parts[0]
                        cookie_val = parts[1].split("&")[0] if "&" in parts[1] else parts[1]
                    elif "|cookie=" in clean_url:
                        parts = clean_url.split("|cookie=")
                        clean_url = parts[0]
                        cookie_val = parts[1].split("&")[0] if "&" in parts[1] else parts[1]

                    url_added = True

                # Inject #EXTHTTP with Cookie, Origin, and Referer exactly matching sample format
                if cookie_val:
                    channel_lines.append(f'#EXTHTTP:{{"cookie":"{cookie_val}","Origin":"https://www.jiotv.com/","Referer":"https://www.jiotv.com/"}}')
                else:
                    channel_lines.append('#EXTHTTP:{"Origin":"https://www.jiotv.com/","Referer":"https://www.jiotv.com/"}')

                channel_lines.append(clean_url)

            except Exception:
                pass

        if not url_added:
            channel_lines.append('#EXTHTTP:{"Origin":"https://www.jiotv.com/","Referer":"https://www.jiotv.com/"}')
            if raw_stream_line:
                channel_lines.append(raw_stream_line)
            else:
                channel_lines.append("http://dummy-link-to-prevent-break")

    except Exception:
        channel_lines.append('#EXTHTTP:{"Origin":"https://www.jiotv.com/","Referer":"https://www.jiotv.com/"}')
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
        res = session.get(PLAYLIST_URL, headers={"User-Agent": "plaYtv/7.1.5"})
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

        print(f"[*] Found {len(target_indices)} channels. Launching multithreading...\n")  

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
                    fallback_lines = [lines[idx].strip(), '#EXTHTTP:{"Origin":"https://www.jiotv.com/","Referer":"https://www.jiotv.com/"}']
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
                new_lines.append('#EXTHTTP:{"Origin":"https://www.jiotv.com/","Referer":"https://www.jiotv.com/"}')
                new_lines.append("http://dummy-link-to-prevent-break")

        output_file = "safe_500_channels.m3u"  
        with open(output_file, "w", encoding="utf-8") as f:  
            f.write("\n".join(new_lines))  

        print(f"\n\n[+] Success! Exactly {len(target_indices)} channels saved as '{output_file}'.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_1000()
