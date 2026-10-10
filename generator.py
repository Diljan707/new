from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import base64
import os
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry
import threading
from bs4 import BeautifulSoup

PLAYLIST_URL = os.environ.get("PLAYLIST_URL")
IP_MANAGER_URL = "https://game.playindia.fun/Jtv/IP.php?id=RiYlIZ"

MAX_CHANNELS = 1000
MAX_WORKERS = 40

counter_lock = threading.Lock()
processed_count = 0

def clear_old_ips(session):
    print("[*] Checking and clearing old IPs from IP Manager...")
    headers = {
        "User-Agent": "Denver1769",
        "Referer": "https://game.playindia.fun/"
    }
    try:
        res = session.get(IP_MANAGER_URL, headers=headers, timeout=10)
        if res.status_code != 200:
            return
        soup = BeautifulSoup(res.text, 'html.parser')
        forms = soup.find_all('form')
        ip_list = []
        for form in forms:
            action_input = form.find('input', {'name': 'action', 'value': 'delete_ip'})
            ip_input = form.find('input', {'name': 'ip'})
            if action_input and ip_input:
                ip_list.append(ip_input.get('value'))
        if not ip_list:
            return
        def delete_single(ip_val):
            data = {'action': 'delete_ip', 'ip': ip_val}
            try:
                session.post(IP_MANAGER_URL, data=data, headers=headers, timeout=5)
            except Exception:
                pass
        with ThreadPoolExecutor(max_workers=15) as executor:
            executor.map(delete_single, ip_list)
        print("[+] All old IPs cleared successfully!\n")
    except Exception as e:
        print(f"[-] Error clearing IPs: {e}")

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

def b64_to_hex(b64_str):
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

    channel_id = ""
    if 'tvg-id="' in extinf_line:
        try:
            channel_id = extinf_line.split('tvg-id="')[1].split('"')[0]
        except Exception:
            pass

    raw_stream_line = ""
    for f in range(i + 1, min(len(lines), i + 5)):
        if lines[f].strip().startswith("http"):
            raw_stream_line = lines[f].strip().split()[0]
            if raw_stream_line.endswith("~"):
                raw_stream_line = raw_stream_line[:-1]
            break
            
    if not channel_id and "id=" in extinf_line:
        try:
            channel_id = extinf_line.split('id="')[1].split('"')[0]
        except Exception:
            pass

    if not channel_id and raw_stream_line:
        if "id=" in raw_stream_line:
            try:
                channel_id = raw_stream_line.split("id=")[1].split("&")[0]
            except Exception:
                pass

    is_hotstar = "hotstar" in extinf_line.lower() or "hotstar" in raw_stream_line.lower() or "jhs" in extinf_line.lower()
    for b in range(max(0, i - 3), i + 4):
        if "hotstar" in lines[b].lower() or "jhs" in lines[b].lower():
            is_hotstar = True
            break

    channel_lines = [extinf_line]

    try:
        key_url = None
        for b in range(max(0, i - 3), i):
            sub_b = lines[b].strip()
            if "inputstream.adaptive.license_key=" in sub_b:
                key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

        user_agent = "Hotstar;in.startv.hotstar/25.02.24.8.11169@Premium Plugx(Android/15)" if is_hotstar else "Denver1769"
        for f in range(i + 1, min(len(lines), i + 4)):
            sub_f = lines[f].strip()
            if sub_f.startswith("#EXTVLCOPT:http-user-agent="):
                user_agent = sub_f.split("=")[1].strip()

        formatted_license_key = None
        if key_url:
            try:
                if '"' in key_url:
                    key_url = key_url.replace('"', "")
                key_res = session.get(key_url, headers={"User-Agent": user_agent}, timeout=3)
                if key_res.status_code == 200:
                    key_json = key_res.json()
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

        if is_hotstar:
            channel_lines.append("#KODIPROP:inputstream=inputstream.adaptive")
            channel_lines.append("#KODIPROP:inputstream.adaptive.manifest_type=mpd")
            channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            
            if formatted_license_key:
                channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={formatted_license_key}")
            elif key_url:
                channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={key_url}")

            channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")
            channel_lines.append("#EXTVLCOPT:http-referrer=https://www.hotstar.com/")
            channel_lines.append("#EXTVLCOPT:http-extra-headers=Origin: https://www.hotstar.com")
            
            cookie_str = "hdntl=exp=1790846295~acl=%2f*~id=af9f2444dbd242ba96e15a82e9d5f668~data=hdntl~hmac=85fbbe3fd86f68e27d194b494a1eab8666d65bf230c58a4231acdbc50e3b2caa"
            if "|cookie=" in raw_stream_line:
                try:
                    cookie_str = raw_stream_line.split("|cookie=")[1].split("&")[0]
                except Exception:
                    pass

            channel_lines.append(f"#EXTVLCOPT:http-cookie={cookie_str}")
            channel_lines.append(f'#EXTHTTP:{{"Origin":"https://www.hotstar.com","Referer":"https://www.hotstar.com/","Cookie":"{cookie_str}"}}')
            
            if raw_stream_line:
                channel_lines.append(raw_stream_line)
            else:
                channel_lines.append("http://dummy-link-to-prevent-break")

        else:
            channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            if formatted_license_key:
                channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={formatted_license_key}")
            elif key_url:
                channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={key_url}")

            channel_lines.append("#EXTVLCOPT:http-user-agent=JioTV/6.0.0 (Linux; Android 11) ExoPlayerLib/2.11.8")
            
            final_stream_url = raw_stream_line
            if raw_stream_line:
                try:
                    headers = {
                        "User-Agent": "Denver1769",
                        "Origin": "https://www.jiotv.com/",
                        "Referer": "https://www.jiotv.com/"
                    }
                    r = session.get(raw_stream_line, headers=headers, allow_redirects=False, timeout=5)
                    if r.status_code in [301, 302, 303, 307, 308] and "location" in r.headers:
                        final_stream_url = r.headers["location"]
                except Exception:
                    pass

            channel_lines.append('#EXTHTTP:{"Origin":"https://www.jiotv.com/","Referer":"https://www.jiotv.com/"}')

            if final_stream_url:
                channel_lines.append(final_stream_url)
            else:
                channel_lines.append("http://dummy-link-to-prevent-break")

    except Exception:
        channel_lines.append("#EXTVLCOPT:http-user-agent=JioTV/6.0.0 (Linux; Android 11) ExoPlayerLib/2.11.8")
        channel_lines.append('#EXTHTTP:{"Origin":"https://www.jiotv.com/","Referer":"https://www.jiotv.com/"}')
        channel_lines.append(raw_stream_line if raw_stream_line else "http://dummy-link-to-prevent-break")

    return channel_lines

def generate_safe_playlist_1000():
    global processed_count
    processed_count = 0
    if not PLAYLIST_URL:
        return

    session = get_robust_session()
    clear_old_ips(session)

    try:
        res = session.get(PLAYLIST_URL, headers={"User-Agent": "Denver1769"})
        if res.status_code != 200:
            return

        lines = res.text.splitlines()  
        all_channels = []
        for i, line in enumerate(lines):  
            if line.strip().startswith("#EXTINF"):  
                all_channels.append((i, line))

        if not all_channels:  
            return  

        target_indices = [item[0] for item in all_channels[:MAX_CHANNELS]]
        print(f"[*] Processing {len(target_indices)} channels with Auto-Redirect resolution...")  

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
                    pass

        new_lines = ["#EXTM3U"]
        for idx in target_indices:
            if idx in channel_results:
                new_lines.extend(channel_results[idx])

        output_file = ".m3u"  
        with open(output_file, "w", encoding="utf-8") as f:  
            f.write("\n".join(new_lines))  

        print(f"\n[+] Success! Final playlist saved as '{output_file}'.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_1000()
    
