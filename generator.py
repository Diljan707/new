from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import os
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urljoin
from bs4 import BeautifulSoup

PLAYLIST_URL = os.environ.get("PLAYLIST_URL", "https://game.playindia.fun/Jtv/qwerty/Playlist.m3u")
IP_MANAGER_URL = "https://game.playindia.fun/Jtv/IP.php?id=xP0xaG"
LCN_LIST_URL = (
    "https://raw.githubusercontent.com/Diljan707/"
    "Automated-/refs/heads/main/dishtv_lcn_list.txt"
)

MAX_CHANNELS = 2000
MAX_WORKERS = 40

def fetch_lcn_dict(session):
    print("[*] Fetching DishTV LCN list...")
    lcn_dict = {}
    try:
        res = session.get(LCN_LIST_URL, timeout=10)
        if res.status_code == 200:
            for line in res.text.splitlines():
                if ":" not in line:
                    continue
                chno, chname = line.split(":", 1)
                chno = chno.strip()
                chname = " ".join(chname.strip().lower().split())
                if chname and chname not in lcn_dict:
                    lcn_dict[chname] = chno
            print(f"[+] Loaded {len(lcn_dict)} LCN mappings!\n")
    except Exception as e:
        print(f"[-] Error fetching LCN list: {e}")
    return lcn_dict

def clean_val(val):
    if not val:
        return ""
    val = val.strip()
    while val and val[-1] in ('"', "'", '}', ']', '~', ','):
        val = val[:-1].strip()
    return val

def remove_group_title(extinf):
    extinf = re.sub(r'\s*group-title="[^"]*"', '', extinf, flags=re.IGNORECASE)
    extinf = re.sub(r"\s*group-title='[^']*'", '', extinf, flags=re.IGNORECASE)
    extinf = re.sub(r'\s*group-title=[^\s,]+', '', extinf, flags=re.IGNORECASE)
    return extinf

def clear_old_ips(session):
    print("[*] Checking IP Manager...")
    headers = {
        "User-Agent": "Denver1769",
        "Referer": "https://game.playindia.fun/"
    }
    try:
        res = session.get(IP_MANAGER_URL, headers=headers, timeout=10)
        if res.status_code != 200:
            return
        soup = BeautifulSoup(res.text, "html.parser")
        ip_list = []
        for form in soup.find_all("form"):
            action_input = form.find("input", {"name": "action", "value": "delete_ip"})
            ip_input = form.find("input", {"name": "ip"})
            if action_input and ip_input and ip_input.get("value"):
                ip_list.append(ip_input["value"])
        if not ip_list:
            return

        def delete_single(ip_val):
            try:
                session.post(
                    IP_MANAGER_URL,
                    data={"action": "delete_ip", "ip": ip_val},
                    headers=headers,
                    timeout=5
                )
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=15) as executor:
            list(executor.map(delete_single, ip_list))
        print("[+] IP Manager cleanup completed.\n")
    except Exception as e:
        print(f"[-] Error checking IP Manager: {e}")

def get_robust_session():
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504]
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

def b64_to_hex(b64_str):
    b64_str = clean_val(b64_str)
    padding = 4 - (len(b64_str) % 4)
    if padding < 4:
        b64_str += "=" * padding
    try:
        return base64.urlsafe_b64decode(b64_str).hex()
    except Exception:
        return b64_str

def resolve_stream_url(url, session, user_agent, is_hotstar, is_vzy):
    url = clean_val(url)
    if not url:
        return ""
    
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip"}
    if is_hotstar:
        headers.update({
            "User-Agent": "Hotstar;in.startv.hotstar/25.02.24.8.11169 (Android/15)",
            "Origin": "https://www.hotstar.com",
            "Referer": "https://www.hotstar.com/",
            "Accept-Encoding": "identity"
        })
    elif is_vzy:
        headers.update({
            "User-Agent": "OTT Navigator/1.7.5.1 (Linux;Android 11; 147es1c) ExoPlayerLib/2.15.1"
        })
    else:
        headers.update({
            "User-Agent": "Denver1769"
        })
    
    try:
        response = session.get(url, headers=headers, allow_redirects=False, timeout=10)
        if response.status_code in [301, 302, 303, 307, 308]:
            loc = response.headers.get("Location")
            if loc:
                loc = clean_val(loc)
                if not loc.startswith("http"):
                    loc = urljoin(url, loc)
                return loc
        elif response.status_code == 200:
            if response.url and "playindia.fun" not in response.url.lower():
                return clean_val(response.url)
    except Exception:
        pass
        
    return url

def process_single_channel(i, lines, session, lcn_dict):
    extinf_line = lines[i].strip()
    extinf_line = remove_group_title(extinf_line)

    chno = ""
    if "," in extinf_line:
        prefix_part, title = extinf_line.split(",", 1)
        title_clean = (
            title.replace(" Digital", "")
            .replace("digital", "")
            .replace("DIGITAL", "")
        )
        if "star sports" not in title_clean.lower():
            title_clean = (
                title_clean.replace(" Hindi", "")
                .replace("hindi", "")
                .replace("HINDI", "")
            )
        channel_title_clean = " ".join(
            title_clean.strip().lower().split()
        )
        chno = lcn_dict.get(channel_title_clean, "")
        if chno:
            if f"({chno})" not in title:
                title = f"{title.strip()} ({chno})"
            if "tvg-chno=" not in prefix_part:
                prefix_part = (
                    prefix_part.strip() + f' tvg-chno="{chno}" ch-number="{chno}"'
                )
            extinf_line = f"{prefix_part},{title}"

    raw_stream_line = ""
    for f in range(i + 1, min(len(lines), i + 5)):
        candidate_line = clean_val(lines[f])
        if candidate_line.startswith("http"):
            raw_stream_line = candidate_line.split()[0]
            raw_stream_line = clean_val(
                raw_stream_line.split('"')[0].split(",")[0]
            )
            break

    lower_text = (extinf_line + raw_stream_line).lower()
    for b in range(max(0, i - 3), min(len(lines), i + 4)):
        lower_text += lines[b].lower()

    is_hotstar = "hotstar" in lower_text or "jhs" in lower_text
    is_vzy = "watcho" in lower_text or "vzy" in lower_text or "oops" in lower_text
    is_sliv = "sliv" in lower_text or "sony" in lower_text or "ten" in lower_text

    try:
        key_url = None
        for b in range(max(0, i - 3), i):
            sub_b = clean_val(lines[b])
            if "inputstream.adaptive.license_key=" in sub_b:
                key_url = clean_val(
                    sub_b.split("inputstream.adaptive.license_key=")[1].split('"')[0]
                )

        if is_hotstar:
            user_agent = "Hotstar;in.startv.hotstar/25.02.24.8.11169 (Android/15)"
        elif is_vzy:
            user_agent = "OTT Navigator/1.7.5.1 (Linux;Android 11; 147es1c) ExoPlayerLib/2.15.1"
        elif is_sliv:
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        else:
            user_agent = "Denver1769"

        formatted_license_key = None
        if key_url:
            try:
                key_url = clean_val(
                    key_url.replace('"', "").replace("'", "")
                )
                key_res = session.get(
                    key_url, headers={"User-Agent": user_agent}, timeout=3
                )
                if key_res.status_code == 200:
                    key_json = key_res.json()
                    key_pairs = []
                    keys_list = key_json.get(
                        "base64", {}
                    ).get("keys", [])
                    for k_obj in keys_list:
                        kid_b64 = clean_val(k_obj.get("kid", ""))
                        k_b64 = clean_val(k_obj.get("k", ""))
                        if kid_b64 and k_b64:
                            key_pairs.append(
                                f"{b64_to_hex(kid_b64)}:"
                                f"{b64_to_hex(k_b64)}"
                            )
                    if key_pairs:
                        formatted_license_key = ",".join(key_pairs)
            except Exception:
                pass

        if not formatted_license_key:
            formatted_license_key = "null:null"

        final_stream_url = ""
        if raw_stream_line:
            resolved = resolve_stream_url(
                raw_stream_line, session, user_agent, is_hotstar, is_vzy
            )
            if resolved:
                final_stream_url = clean_val(
                    resolved.split('"')[0].split(",")[0]
                )

        if not final_stream_url:
            final_stream_url = raw_stream_line

        channel_lines = [extinf_line]
        is_mpd_link = ".mpd" in final_stream_url.lower()

        channel_lines.append(
            "#KODIPROP:inputstream=inputstream.adaptive"
        )
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.manifest_type="
            + ("mpd" if is_mpd_link else "hls")
        )
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.max_bandwidth=0"
        )
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.stream_selection_type=automatic"
        )
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.max_buffer_time=1"
        )
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.buffer_segment_size=1"
        )
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.live_delay=0"
        )

        # Exact working format matching user's provided sample
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.license_type=clearkey"
        )
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.license_key="
            + formatted_license_key
        )
        
        # Clean URL with query token attached directly
        if "jiotvmblive.cdn.jio.com" in final_stream_url or "jiotvpllive.cdn.jio.com" in final_stream_url:
            base_url = clean_val(final_stream_url.split("|")[0].split('"')[0].split("?")[0])
            token_query = ""
            if "__hdnea__=" in final_stream_url:
                token_query = final_stream_url.split("__hdnea__=")[1].split()[0].split('"')[0]
            if token_query:
                final_stream_url = f"{base_url}?__hdnea__={token_query}"

        channel_lines.append(final_stream_url)

        return chno, channel_lines

    except Exception as e:
        print(f"[-] Channel processing error at line {i}: {e}")
        return None, None

def generate_safe_playlist_1000():
    session = get_robust_session()
    clear_old_ips(session)
    lcn_dict = fetch_lcn_dict(session)

    try:
        res = session.get(
            PLAYLIST_URL, headers={"User-Agent": "Denver1769"}, timeout=30
        )
        if res.status_code != 200:
            print(f"[-] Playlist HTTP status: {res.status_code}")
            return

        lines = res.text.splitlines()
        all_channels = [
            (i, line) for i, line in enumerate(lines) if line.strip().startswith("#EXTINF")
        ]
        if not all_channels:
            print("[-] No channels found in playlist.")
            return

        target_indices = [item[0] for item in all_channels[:MAX_CHANNELS]]
        print(f"[*] Processing and verifying {len(target_indices)} channels...")

        processed_channels = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    process_single_channel, idx, lines, session, lcn_dict
                ): idx for idx in target_indices
            }
            for future in as_completed(futures):
                try:
                    chno, res_lines = future.result()
                    if res_lines:
                        try:
                            sort_key = int(chno)
                        except (ValueError, TypeError):
                            sort_key = 99999
                        processed_channels.append((sort_key, res_lines))
                except Exception as e:
                    print(f"[-] Channel task failed: {e}")

        processed_channels.sort(key=lambda x: x[0])
        new_lines = ["#EXTM3U"]
        for _, res_lines in processed_channels:
            new_lines.extend(res_lines)

        output_file = "m3u"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        print(f"\n[+] Success! Verified and saved {len(processed_channels)} channels as '{output_file}'.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_1000()
