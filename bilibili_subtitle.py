import json
import re
import time
import hashlib
import argparse
import sys
import urllib.parse
from pathlib import Path


import requests


class BilibiliAPIError(Exception):
    pass


class BilibiliAPI:
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    RETRIES = 3
    BASE_URL = "https://api.bilibili.com"

    def __init__(self, cookie: str = ""):
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.USER_AGENT})
        if cookie:
            for part in cookie.split(";"):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    self._session.cookies.set(k.strip(), v.strip())
        self._wbi_keys = None
        self._wbi_keys_ts = 0

    @staticmethod
    def normalize_id(video_id: str) -> str:
        video_id = video_id.strip()
        if video_id.startswith("BV"):
            return video_id
        aid = video_id
        if aid.startswith("av"):
            aid = aid[2:]
        if aid.isdigit():
            return BilibiliAPI._aid_to_bvid(int(aid))
        raise BilibiliAPIError(f"无法识别的视频 ID: {video_id}")

    @staticmethod
    def _aid_to_bvid(aid: int) -> str:
        table = "fZodR9XQDSUm21yCkr6zBqiveYah8bt4xsWpHnJE7jL5VG3guMTKNPAwcF"
        aid = (aid ^ 177451812) + 8728348608
        bvid = ['B', 'V', '1', '1', '1', '4', '1', '1', '1', '7', '1', '1']
        pos = [11, 10, 3, 8, 4, 6]
        for i in range(6):
            bvid[pos[i]] = table[(aid // 58 ** i) % 58]
        return ''.join(bvid)

    def get_video_info(self, video_id: str) -> dict:
        bvid = self.normalize_id(video_id)
        params = {"bvid": bvid}
        data = self._request("/x/web-interface/view", params)
        vinfo = data["data"]
        return {
            "title": vinfo["title"],
            "bvid": bvid,
            "aid": vinfo["aid"],
            "cid": vinfo["cid"],
            "pages": [
                {"cid": p["cid"], "title": p["part"], "page": p["page"]}
                for p in vinfo.get("pages", [])
            ],
        }

    def _request(self, path: str, params: dict = None) -> dict:
        url = self.BASE_URL + path
        last_err = None
        for attempt in range(1, self.RETRIES + 1):
            try:
                resp = self._session.get(url, params=params, timeout=15)
                if resp.status_code == 429:
                    time.sleep(5 * attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 0:
                    raise BilibiliAPIError(
                        f"API 返回错误 (code={data.get('code')}): {data.get('message', '')}"
                    )
                return data
            except (requests.RequestException, json.JSONDecodeError) as e:
                last_err = e
                if attempt < self.RETRIES:
                    time.sleep(2 ** (attempt - 1))
        raise BilibiliAPIError(f"请求失败（重试 {self.RETRIES} 次）: {last_err}")

    def _get_wbi_keys(self):
        if self._wbi_keys is not None and time.time() - self._wbi_keys_ts < 3600:
            return self._wbi_keys
        try:
            resp = self._session.get(f"{self.BASE_URL}/x/web-interface/nav", timeout=15)
            nav_data = resp.json()
            wbi_img = nav_data.get("data", {}).get("wbi_img", {})
            img_url = wbi_img.get("img_url", "")
            sub_url = wbi_img.get("sub_url", "")
            if not img_url or not sub_url:
                return None, None
            img_key = img_url.rsplit("/", 1)[1].split(".")[0]
            sub_key = sub_url.rsplit("/", 1)[1].split(".")[0]
            self._wbi_keys = (img_key, sub_key)
            self._wbi_keys_ts = time.time()
            return img_key, sub_key
        except Exception:
            return None, None

    @staticmethod
    def _sign_wbi(params: dict, img_key: str, sub_key: str) -> dict:
        params = {**(params or {})}
        mix_key = hashlib.md5(f"{img_key}{sub_key}".encode()).hexdigest()
        params["wts"] = int(time.time())
        sorted_params = sorted(params.items())
        query = urllib.parse.urlencode(sorted_params)
        sign = hashlib.md5(f"{query}{mix_key}".encode()).hexdigest()
        params["w_rid"] = sign
        return params

    def _parse_subtitles(self, data: dict) -> list:
        subtitles = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
        if not subtitles:
            return []
        result = []
        for sub in subtitles:
            url = sub.get("subtitle_url", "")
            if not url:
                continue
            if not url.startswith("http"):
                url = "https:" + url
            result.append({
                "lan": sub.get("lan", ""),
                "lan_doc": sub.get("lan_doc", ""),
                "url": url,
            })
        return result

    def get_subtitle_list(self, bvid: str, cid: int) -> list:
        try:
            data = self._request("/x/player/v2", {"bvid": bvid, "cid": cid})
            result = self._parse_subtitles(data)
            if result:
                return result
        except BilibiliAPIError:
            pass
        img_key, sub_key = self._get_wbi_keys()
        if img_key:
            params = self._sign_wbi({"bvid": bvid, "cid": cid}, img_key, sub_key)
            data = self._request("/x/player/wbi/v2", params)
            result = self._parse_subtitles(data)
        return result

    def download_subtitle(self, url: str) -> list:
        if "?" in url:
            url = f"{url}&_={int(time.time() * 1000)}"
        last_err = None
        for attempt in range(1, self.RETRIES + 1):
            try:
                resp = self._session.get(url, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                return data.get("body", [])
            except (requests.RequestException, json.JSONDecodeError) as e:
                last_err = e
                if attempt < self.RETRIES:
                    time.sleep(2 ** (attempt - 1))
        raise BilibiliAPIError(f"字幕下载失败（重试 {self.RETRIES} 次）: {last_err}")


class SubtitleProcessor:
    CHINESE_KEYWORDS = ("中文", "zh", "chi", "汉语", "国语")

    @classmethod
    def extract_chinese(cls, subtitle_list: list) -> list:
        candidates = []
        for sub in subtitle_list:
            lan_doc = sub.get("lan_doc", "")
            lan = sub.get("lan", "")
            if any(kw in lan_doc.lower() or kw in lan.lower() for kw in cls.CHINESE_KEYWORDS):
                candidates.append(sub)
        if not candidates:
            raise BilibiliAPIError("未找到中文字幕")
        if len(candidates) == 1:
            return candidates[0]
        ai = [s for s in candidates if s.get("lan", "").startswith("ai-")]
        if ai:
            return ai[0]
        return candidates[0]

    @classmethod
    def process_segments(cls, segments: list) -> list:
        segments.sort(key=lambda s: s["from"])
        last_content = None
        result = []
        for seg in segments:
            content = seg.get("content", "").strip()
            if not content:
                continue
            if content == last_content:
                continue
            result.append({
                "from": seg["from"],
                "to": seg["to"],
                "content": content,
            })
            last_content = content
        return result

    @staticmethod
    def format_ts(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"


class FileWriter:
    ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')

    @classmethod
    def _sanitize_title(cls, title: str) -> str:
        return cls.ILLEGAL_CHARS.sub("_", title).strip().strip('.')

    @classmethod
    def write_plain(cls, segments: list, title: str, output_dir: str = ".") -> str:
        safe_title = cls._sanitize_title(title)
        filepath = Path(output_dir) / f"{safe_title}.txt"
        text = "\n".join(seg["content"] for seg in segments)
        filepath.write_text(text, encoding="utf-8")
        return str(filepath)

    @classmethod
    def write_timestamped(cls, segments: list, title: str, output_dir: str = ".") -> str:
        safe_title = cls._sanitize_title(title)
        filepath = Path(output_dir) / f"{safe_title}-带时间戳.txt"
        lines = []
        for seg in segments:
            ts = SubtitleProcessor.format_ts(seg["from"])
            te = SubtitleProcessor.format_ts(seg["to"])
            lines.append(f"[{ts} --> {te}] {seg['content']}")
        filepath.write_text("\n".join(lines), encoding="utf-8")
        return str(filepath)


def verify_cookie(cookie: str) -> bool:
    """实测验证 Cookie 是否真实有效，而非靠过期时间推测。"""
    if not cookie:
        return False
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": BilibiliAPI.USER_AGENT})
        for part in cookie.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                s.cookies.set(k.strip(), v.strip())
        resp = s.get("https://api.bilibili.com/x/web-interface/nav", timeout=15)
        data = resp.json()
        return data.get("data", {}).get("isLogin", False)
    except Exception:
        return False


COOKIE_FILE = Path(__file__).parent / ".bilibili_cookie"


def save_cookie(cookie: str):
    COOKIE_FILE.write_text(cookie, encoding="utf-8")


def load_cookie() -> str:
    if COOKIE_FILE.exists():
        return COOKIE_FILE.read_text(encoding="utf-8").strip()
    return ""


COOKIE_HELP = """\
获取Cookie的方法：
  浏览器打开 bilibili.com → F12 → 应用(Application) → Cookie
  复制 SESSDATA 和 buvid3 的值

  示例：--cookie "SESSDATA=xxx; buvid3=xxx"
"""


def prompt_cookie_if_needed(cookie: str) -> str:
    if cookie and verify_cookie(cookie):
        return cookie

    if cookie:
        print("  [Cookie 已验证无效，请重新输入]")
    else:
        print("  [未提供Cookie]")

    print(COOKIE_HELP)
    reply = input("  是否输入Cookie？(y/N): ").strip().lower()
    if reply != "y":
        return cookie
    sessdata = input("  请输入 SESSDATA: ").strip()
    buvid3 = input("  请输入 buvid3: ").strip()
    if not sessdata or not buvid3:
        print("  输入为空，跳过。")
        return cookie
    new_cookie = f"SESSDATA={sessdata}; buvid3={buvid3}"
    if verify_cookie(new_cookie):
        save_cookie(new_cookie)
        print("  [Cookie 已验证有效，已保存到本地]")
    else:
        print("  [警告：Cookie 未通过 API 验证，可能无效]")
        save_cookie(new_cookie)
    return new_cookie


def fetch_subtitles_with_consensus(
    api, bvid: str, cid: int, max_attempts: int, interval: float
) -> list:
    seen = {}
    for attempt in range(1, max_attempts + 1):
        subs = api.get_subtitle_list(bvid, cid)
        if not subs:
            continue
        ch = SubtitleProcessor.extract_chinese(subs)
        raw = api.download_subtitle(ch["url"])
        if not raw:
            continue
        fingerprint = raw[0]["content"].strip()[:60]

        if fingerprint in seen:
            return raw

        seen[fingerprint] = raw
        if attempt < max_attempts:
            time.sleep(interval)

    if seen:
        return max(seen.values(), key=len)
    return []


def process_one(
    video_id: str, page: int, cookie: str,
    output_dir: str, retry: int, retry_interval: float
) -> str:
    api = BilibiliAPI(cookie=cookie)
    info = api.get_video_info(video_id)

    if page > 1:
        if page > len(info["pages"]):
            raise BilibiliAPIError(f"该视频只有 {len(info['pages'])}P")
        cid = info["pages"][page - 1]["cid"]
    else:
        cid = info["cid"]

    raw_segs = fetch_subtitles_with_consensus(
        api, info["bvid"], cid, retry, retry_interval
    )
    if not raw_segs:
        raise BilibiliAPIError("没有找到字幕")

    segs = SubtitleProcessor.process_segments(raw_segs)
    p1 = FileWriter.write_plain(segs, info["title"], output_dir)
    p2 = FileWriter.write_timestamped(segs, info["title"], output_dir)
    return f"纯文本: {p1}\n时间戳: {p2}"


def main():
    parser = argparse.ArgumentParser(description="下载B站视频中文字幕")
    parser.add_argument("video_id", nargs="*", help="BV号 / AV号 / 完整URL，支持多个")
    parser.add_argument("-o", "--output", default=".", help="输出目录（默认当前目录）")
    parser.add_argument("-p", "--page", type=int, default=1, help="分P编号（默认1）")
    parser.add_argument("--cookie", default="", help="B站登录Cookie (SESSDATA=xxx; buvid3=xxx)")
    parser.add_argument("--retry", type=int, default=3, help="字幕一致性尝试次数（默认3）")
    parser.add_argument("--retry-interval", type=float, default=3, help="重试间隔秒数（默认3）")
    args = parser.parse_args()

    video_ids = args.video_id
    if not video_ids:
        raw = input("请输入B站视频 BV号 或 AV号（多个用空格分隔）: ").strip()
        video_ids = raw.split()
    cleaned = []
    for vid in video_ids:
        if "/video/" in vid:
            vid = vid.split("/video/")[1].split("/")[0].split("?")[0]
        cleaned.append(vid)

    cookie = args.cookie
    if not cookie:
        saved = load_cookie()
        if saved:
            cookie = saved
    else:
        save_cookie(cookie)

    for i, vid in enumerate(cleaned):
        if len(cleaned) > 1:
            print(f"\n[{i + 1}/{len(cleaned)}] {vid}")
        try:
            cookie = prompt_cookie_if_needed(cookie)
            result = process_one(
                vid, args.page, cookie, args.output,
                args.retry, args.retry_interval
            )
            print(result)
        except BilibiliAPIError as e:
            print(f"错误: {e}", file=sys.stderr)
            if i < len(cleaned) - 1:
                print("继续处理下一个视频...")
        except Exception as e:
            print(f"意外错误: {e}", file=sys.stderr)
            if i < len(cleaned) - 1:
                print("继续处理下一个视频...")
        if i < len(cleaned) - 1:
            time.sleep(2)


if __name__ == "__main__":
    main()
