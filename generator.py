from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import os
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urljoin
from bs4 import BeautifulSoup

PLAYLIST_URL = os.environ.get("PLAYLIST_URL")
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
                chno =chno.strip()
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
    # Removes group-title attribute from EXTINF line
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

def resolve_stream_url(url, session, user_agent, is_hotstar, is_sliv):
    url = clean_val(url)
    if not url:
        return url
    headers = {"User-Agent": user_agent}
    if is_hotstar:
        headers.update({
            "User-Agent": (
                "Hotstar;in.startv.hotstar/"
                "25.02.24.8.11169 (Android/15)"
            ),
            "Origin": "https://www.hotstar.com",
            "Referer": "https://www.hotstar.com/",
            "Accept-Encoding": "identity"
        })
    elif is_sliv:
        headers.update({
            "Origin": "https://www.sonyliv.com",
            "Referer": "https://www.sonyliv.com/"
        })
    
    response = None
    try:
        response = session.get(
            url, headers=headers, allow_redirects=True, timeout=7, stream=True
        )
        if response.history and response.url:
            if "playindia.fun" not in response.url.lower():
                final_url = response.url
                response.close()
                return clean_val(final_url)
        
        if response.status_code == 200:
            try:
                res_text = response.text
                nested_links = []
                for line in res_text.splitlines():
                    line = clean_val(line)
                    if (
                        "http" in line
                        and ("m3u8" in line.lower() or "mpd" in line.lower())
                        and "playindia.fun" not in line.lower()
                    ):
                        idx = line.find("http")
                        clean_link = clean_val(line[idx:].split()[0])
                        nested_links.append(clean_link)
                if nested_links:
                    chosen_link = clean_val(nested_links[-1])
                    if not chosen_link.startswith("http"):
                        chosen_link = urljoin(response.url, chosen_link)
                    response.close()
                    return chosen_link
            except Exception:
                pass
        
        if response.url and "playindia.fun" not in response.url.lower():
            final_url = clean_val(response.url)
            if not final_url.startswith("http"):
                final_url = urljoin(url, final_url)
            response.close()
            return final_url
    except Exception as e:
        print(f"[-] Stream resolution error for {url}: {e}")
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
    # Fallback to original URL if any redirection/resolution error occurs
    return url

def process_single_channel(i, lines, session, lcn_dict):
    extinf_line = lines[i].strip()
    
    # Remove group-title as requested
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

    channel_id = ""
    if 'tvg-id="' in extinf_line:
        try:
            channel_id = (
                extinf_line.split('tvg-id="')[1].split('"')[0]
            )
        except Exception:
            pass

    raw_stream_line = ""
    for f in range(i + 1, min(len(lines), i + 5)):
        candidate_line = clean_val(lines[f])
        if candidate_line.startswith("http"):
            raw_stream_line = candidate_line.split()[0]
            raw_stream_line = clean_val(
                raw_stream_line.split('"')[0].split(",")[0]
            )
            break

    if not channel_id and 'id="' in extinf_line:
        try:
            channel_id = extinf_line.split('id="')[1].split('"')[0]
        except Exception:
            pass

    if not channel_id and raw_stream_line and "id=" in raw_stream_line:
        try:
            channel_id = (
                raw_stream_line.split("id=")[1].split("&")[0]
            )
        except Exception:
            pass

    lower_text = (extinf_line + raw_stream_line).lower()
    for b in range(max(0, i - 3), min(len(lines), i + 4)):
        lower_text += lines[b].lower()

    is_hotstar = "hotstar" in lower_text or "jhs" in lower_text
    is_sliv = (
        "sliv" in lower_text or "sony" in lower_text or "ten" in lower_text
    )

    channel_lines = [extinf_line]
    try:
        key_url = None
        for b in range(max(0, i - 3), i):
            sub_b = clean_val(lines[b])
            if "inputstream.adaptive.license_key=" in sub_b:
                key_url = clean_val(
                    sub_b.split("inputstream.adaptive.license_key=")[1].split('"')[0]
                )

        if is_hotstar:
            user_agent = (
                "Hotstar;in.startv.hotstar/"
                "25.02.24.8.11169 (Android/15)"
            )
        elif is_sliv:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
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

        final_stream_url = raw_stream_line
        if raw_stream_line:
            resolved = resolve_stream_url(
                raw_stream_line, session, user_agent, is_hotstar, is_sliv
            )
            if resolved:
                final_stream_url = clean_val(
                    resolved.split('"')[0].split(",")[0]
                )

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
            "#KODIPROP:inputstream.adaptive.max_buffer_time=300"
        )
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.buffer_segment_size=1000"
        )
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.live_delay=0"
        )

        if is_hotstar:
            cookie_str = ""
            for check_line in (
                [raw_stream_line]
                + lines[max(0, i - 2):min(len(lines), i + 3)]
            ):
                check_line = clean_val(check_line)
                if "hdntl=" in check_line:
                    try:
                        for part in check_line.split("hdntl=")[1:]:
                            candidate = clean_val(
                                part.split()[0].split('"')[0]
                            )
                            if "exp=" in candidate:
                                cookie_str = (
                                    "hdntl=" + clean_val(candidate.split("&")[0])
                                )
                                break
                    except Exception:
                        pass
                if cookie_str:
                    break

            if not cookie_str:
                cookie_str = (
                    "hdntl=exp=1791763208~acl=%2f*"
                    "~id=ce6ecdabc53ea306cc7be95fa7a1b49c"
                    "~data=hdntl"
                    "~hmac=8a7405e9c3a1f2880ac44abb4e3fee31"
                    "d750b5c4d6d4bfaa67bac50b175140a1"
                )

            base_url = clean_val(
                final_stream_url.split("|")[0].split('"')[0]
            )
            if is_mpd_link:
                channel_lines.append(
                    "#KODIPROP:inputstream.adaptive.license_type=clearkey"
                )
                channel_lines.append(
                    "#KODIPROP:inputstream.adaptive.license_key="
                    + formatted_license_key
                )
                pipe_headers = (
                    f"User-Agent={user_agent}"
                    "&Accept-Encoding=identity"
                    "&X-Denver-Secure=true"
                    "&Host=livetv.hotstar.com"
                    "&Connection=Keep-Alive"
                    f"&Cookie={cookie_str}"
                )
            else:
                pipe_headers = (
                    f"User-Agent={user_agent}"
                    "&Origin=https://www.hotstar.com"
                    "&Referer=https://www.hotstar.com/"
                    f"&Cookie={cookie_str}"
                )
            channel_lines.append(
                clean_val(f"{base_url}|{pipe_headers}")
            )

        elif is_sliv:
            if is_mpd_link:
                channel_lines.append(
                    "#KODIPROP:inputstream.adaptive.license_type=clearkey"
                )
                channel_lines.append(
                    "#KODIPROP:inputstream.adaptive.license_key="
                    + formatted_license_key
                )
                channel_lines.append(
                    f"#EXTVLCOPT:http-user-agent={user_agent}"
                )
                channel_lines.append(
                    "#EXTVLCOPT:http-referrer=https://www.sonyliv.com/"
                )
                channel_lines.append(
                    "#EXTVLCOPT:http-extra-headers="
                    "Origin: https://www.sonyliv.com"
                )
                channel_lines.append(
                    clean_val(final_stream_url)
                    if final_stream_url
                    else "http://dummy-link-to-prevent-break"
                )
            else:
                channel_lines.append(
                    "#KODIPROP:inputstream.adaptive.license_type=clearkey"
                )
                channel_lines.append(
                    "#KODIPROP:inputstream.adaptive.license_key="
                    + formatted_license_key
                )
                channel_lines.append(
                    f"#EXTVLCOPT:http-user-agent={user_agent}"
                )
                jio_cookie = ""
                for check_line in (
                    [raw_stream_line]
                    + lines[max(0, i - 2):min(len(lines), i + 3)]
                ):
                    check_line = clean_val(check_line)
                    if "hdnea=" in check_line:
                        try:
                            for part in check_line.split("hdnea=")[1:]:
                                candidate = clean_val(part.split()[0])
                                if "exp=" in candidate or "st=" in candidate:
                                    jio_cookie = (
                                        "hdnea=" + clean_val(candidate.split("&")[0])
                                    )
                                    break
                        except Exception:
                            pass
                    if jio_cookie:
                        break

                if jio_cookie:
                    channel_lines.append(
                        f"#EXTVLCOPT:http-cookie={jio_cookie}"
                    )
                    channel_lines.append(
                        '#EXTHTTP:{"Origin":"https://www.jiotv.com/",'
                        '"Referer":"https://www.jiotv.com/",'
                        f'"Cookie":"{jio_cookie}",'
                        '"Connection":"keep-alive"}'
                    )
                else:
                    channel_lines.append(
                        '#EXTHTTP:{"Origin":"https://www.jiotv.com/",'
                        '"Referer":"https://www.jiotv.com/",'
                        '"Connection":"keep-alive"}'
                    )
                channel_lines.append(
                    clean_val(final_stream_url)
                    if final_stream_url
                    else "http://dummy-link-to-prevent-break"
                )
        else:
            channel_lines.append(
                "#KODIPROP:inputstream.adaptive.license_type=clearkey"
            )
            channel_lines.append(
                "#KODIPROP:inputstream.adaptive.license_key="
                + formatted_license_key
            )
            channel_lines.append(
                f"#EXTVLCOPT:http-user-agent={user_agent}"
            )
            channel_lines.append(
                clean_val(raw_stream_line)
                if raw_stream_line
                else "http://dummy-link-to-prevent-break"
            )

    except Exception as e:
        print(f"[-] Channel processing error at line {i}: {e}")
        # Fallback to original raw stream and data on any unexpected error
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.license_type=clearkey"
        )
        channel_lines.append(
            "#KODIPROP:inputstream.adaptive.license_key=" + formatted_license_key
        )
        channel_lines.append(
            f"#EXTVLCOPT:http-user-agent={user_agent}"
        )
        channel_lines.append(
            clean_val(raw_stream_line)
            if raw_stream_line
            else "http://dummy-link-to-prevent-break"
        )

    return chno, channel_lines

def generate_safe_playlist_1000():
    if not PLAYLIST_URL:
        print("[-] PLAYLIST_URL environment variable is missing.")
        return

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
        print(f"[*] Processing {len(target_indices)} channels...")

        processed_channels = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    process_single_channel, idx, lines, session, lcn_dict
                ): idx for idx in target_indices
    
