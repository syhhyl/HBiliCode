from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from pathlib import Path

try:
    import qrcode
except ImportError:  # pragma: no cover
    qrcode = None


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "user-agent": USER_AGENT,
}
APP_KEY = "aae92bc66f3edfab"
APP_SEC = "af125a0d5279fd576c1b4418a3e8276d"
DEFAULT_AREA_ID = "235"


SESSION_FILE = Path("session.json")


def ensure_private_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def load_session() -> dict:
    if not SESSION_FILE.exists():
        return {}
    try:
        ensure_private_permissions(SESSION_FILE)
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"读取会话文件失败，将重新登录: {exc}", file=sys.stderr)
        return {}


def save_session(data: dict) -> None:
    temp_file = SESSION_FILE.with_suffix(".tmp")
    temp_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ensure_private_permissions(temp_file)
    os.replace(temp_file, SESSION_FILE)
    ensure_private_permissions(SESSION_FILE)


def clear_session() -> None:
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def app_sign(params: dict[str, object]) -> dict[str, object]:
    signed = dict(params)
    signed["appkey"] = APP_KEY
    signed = dict(sorted(signed.items()))
    query = urllib.parse.urlencode(signed)
    signed["sign"] = hashlib.md5((query + APP_SEC).encode()).hexdigest()
    return signed


def build_cookie_header(cookies: dict[str, str] | None) -> str | None:
    if not cookies:
        return None
    return "; ".join(f"{key}={value}" for key, value in cookies.items())


def http_json(
    method: str,
    url: str,
    *,
    params=None,
    data=None,
    cookies=None,
    with_cookies: bool = False,
) -> dict | tuple[dict, dict[str, str]]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    request_headers = dict(HEADERS)
    cookie_header = build_cookie_header(cookies)
    if cookie_header:
        request_headers["Cookie"] = cookie_header

    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()

    request = urllib.request.Request(
        url, headers=request_headers, data=body, method=method
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if not with_cookies:
            return payload
        cookie_jar = SimpleCookie()
        for raw_header in response.headers.get_all("Set-Cookie", []):
            cookie_jar.load(raw_header)
        response_cookies = {key: morsel.value for key, morsel in cookie_jar.items()}
        return payload, response_cookies


def print_ascii_qr(content: str) -> None:
    print("登录链接:", flush=True)
    print(content, flush=True)
    if not content:
        return
    if qrcode is None:
        print(
            "未安装 qrcode，当前只能显示登录链接。建议执行: pip install -r requirements.txt",
            flush=True,
        )
        return

    print("请使用 Bilibili App 扫码：", flush=True)
    qr = qrcode.QRCode(border=1)
    qr.add_data(content)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def get_login_qr() -> dict:
    payload = http_json(
        "GET", "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
    )
    if payload.get("code") != 0:
        raise RuntimeError(
            payload.get("message") or payload.get("msg") or "获取二维码失败"
        )
    return payload["data"]


def poll_login_status(qrcode_key: str) -> tuple[dict, dict[str, str]]:
    return http_json(
        "GET",
        "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
        params={"qrcode_key": qrcode_key},
        with_cookies=True,
    )


def fetch_room_id(cookies: dict[str, str]) -> str:
    uid = cookies.get("DedeUserID")
    if uid:
        payload = http_json(
            "GET",
            "https://api.live.bilibili.com/room/v2/Room/room_id_by_uid",
            params={"uid": uid},
            cookies=cookies,
        )
        if payload.get("code") == 0:
            return str(payload["data"]["room_id"])
        if payload.get("code") == 404:
            raise RuntimeError("该账号未开通直播间，请先去 B 站开通")

    payload = http_json(
        "GET", "https://api.bilibili.com/x/web-interface/nav", cookies=cookies
    )
    if payload.get("code") != 0:
        raise RuntimeError("获取房间号失败")
    room_id = str(payload["data"].get("live_room", {}).get("roomid", ""))
    if room_id in {"", "0"}:
        raise RuntimeError("该账号未开通直播间")
    return room_id


def fetch_room_info(room_id: str, cookies: dict[str, str] | None = None) -> dict:
    payload = http_json(
        "GET",
        "https://api.live.bilibili.com/room/v1/Room/get_info",
        params={"room_id": room_id},
        cookies=cookies,
    )
    if payload.get("code") != 0:
        raise RuntimeError(
            payload.get("message") or payload.get("msg") or "获取直播间信息失败"
        )
    return payload.get("data", {})


def fetch_user_profile(cookies: dict[str, str]) -> dict:
    payload = http_json(
        "GET", "https://api.bilibili.com/x/web-interface/nav", cookies=cookies
    )
    if payload.get("code") != 0:
        raise RuntimeError("获取用户信息失败")
    data = payload["data"]
    return {
        "uid": str(data.get("mid", "")),
        "uname": data.get("uname", ""),
        "csrf": cookies.get("bili_jct", ""),
        "cookies": cookies,
    }


def session_is_valid(session: dict) -> bool:
    cookies = session.get("cookies")
    if not cookies:
        return False
    try:
        payload = http_json(
            "GET", "https://api.bilibili.com/x/web-interface/nav", cookies=cookies
        )
    except Exception as exc:
        print(f"登录态校验失败，将重新登录: {exc}", file=sys.stderr)
        return False
    return payload.get("code") == 0 and bool(payload.get("data", {}).get("isLogin"))


def qr_login() -> dict:
    qr_data = get_login_qr()
    print_ascii_qr(qr_data["url"])
    print("等待扫码...", flush=True)

    last_status = None
    idle_ticks = 0
    poll_failures = 0
    while True:
        try:
            payload, cookies = poll_login_status(qr_data["qrcode_key"])
            poll_failures = 0
        except Exception as exc:
            poll_failures += 1
            if poll_failures == 1 or poll_failures % 5 == 0:
                print(f"登录状态轮询失败，2 秒后重试: {exc}", flush=True)
            time.sleep(2)
            continue

        code = payload.get("data", {}).get("code")

        if code == 0:
            profile = fetch_user_profile(cookies)
            room_id = fetch_room_id(cookies)
            try:
                room_info = fetch_room_info(room_id, cookies)
            except Exception:
                room_info = {}
            session = {
                "uid": profile["uid"],
                "uname": profile["uname"],
                "csrf": profile["csrf"],
                "room_id": room_id,
                "area_id": str(
                    room_info.get("area_v2_id")
                    or room_info.get("area_id")
                    or DEFAULT_AREA_ID
                ),
                "cookies": cookies,
            }
            save_session(session)
            print(f"登录成功: {session['uname']}", flush=True)
            return session

        if code == 86101:
            idle_ticks += 1
            if idle_ticks % 10 == 0:
                print("仍在等待扫码...", flush=True)
        elif code == 86090 and code != last_status:
            print("已扫码，请在手机上确认", flush=True)
        elif code == 86038:
            raise RuntimeError("二维码已过期，请重新运行脚本")
        elif code not in {86101, 86090}:
            message = (
                payload.get("data", {}).get("message")
                or payload.get("message")
                or "登录失败"
            )
            raise RuntimeError(message)

        last_status = code
        time.sleep(1.5)


def ensure_session() -> dict:
    session = load_session()
    if session.get("cookies") and session.get("csrf") and session.get("room_id"):
        if session_is_valid(session):
            return session
        clear_session()
        print("登录态已失效，正在重新扫码登录...", flush=True)
    return qr_login()


def get_start_live_version(cookies: dict[str, str]) -> tuple[int, dict]:
    payload = http_json(
        "GET", "https://api.bilibili.com/x/report/click/now", cookies=cookies
    )
    if payload.get("code") != 0:
        raise RuntimeError(
            payload.get("message") or payload.get("msg") or "获取时间戳失败"
        )
    ts = payload["data"]["now"]

    version_payload = http_json(
        "GET",
        "https://api.live.bilibili.com/xlive/app-blink/v1/liveVersionInfo/getHomePageLiveVersion",
        params=app_sign({"system_version": 2, "ts": ts}),
        cookies=cookies,
    )
    if version_payload.get("code") != 0:
        raise RuntimeError(
            version_payload.get("message")
            or version_payload.get("msg")
            or "获取版本失败"
        )
    return ts, version_payload["data"]


def start_live(session: dict) -> dict:
    ts, version_data = get_start_live_version(session["cookies"])

    candidate_area_ids: list[str] = []

    for value in (session.get("area_id"), DEFAULT_AREA_ID):
        if value is None:
            continue
        area_id = str(value).strip()
        if area_id and area_id not in candidate_area_ids:
            candidate_area_ids.append(area_id)

    try:
        room_info = fetch_room_info(session["room_id"], session["cookies"])
        for value in (room_info.get("area_v2_id"), room_info.get("area_id")):
            if value is None:
                continue
            area_id = str(value).strip()
            if area_id and area_id not in candidate_area_ids:
                candidate_area_ids.append(area_id)
    except Exception:
        pass

    last_error = "开播失败"
    for area_id in candidate_area_ids:
        payload = {
            "room_id": session["room_id"],
            "platform": "pc_link",
            "area_v2": area_id,
            "backup_stream": "0",
            "csrf_token": session["csrf"],
            "csrf": session["csrf"],
            "build": version_data["build"],
            "version": version_data["curr_version"],
            "ts": ts,
        }
        data = http_json(
            "POST",
            "https://api.live.bilibili.com/room/v1/Room/startLive",
            data=app_sign(payload),
            cookies=session["cookies"],
        )
        if data.get("code") == 60024:
            return {"code": 60024, "qr": data.get("data", {}).get("qr", "")}
        if data.get("code") == 0:
            session["area_id"] = area_id
            save_session(session)
            return extract_streams(data["data"], session["room_id"])
        last_error = data.get("message") or data.get("msg") or "开播失败"

    raise RuntimeError(last_error)


def extract_streams(data: dict, room_id: str) -> dict:
    rtmp_data = data.get("rtmp", {})
    protocols = data.get("protocols", [])

    result = {
        "room_id": room_id,
        "rtmp1": {
            "addr": rtmp_data.get("addr", ""),
            "code": rtmp_data.get("code", ""),
        },
        "rtmp2": {"addr": "", "code": ""},
        "srt": {"addr": "", "code": ""},
    }

    for item in protocols:
        if (
            item.get("protocol") == "rtmp"
            and item.get("addr")
            and item.get("code")
            and not result["rtmp2"]["addr"]
        ):
            result["rtmp2"] = {"addr": item["addr"], "code": item["code"]}
        if (
            item.get("protocol") == "srt"
            and item.get("addr")
            and item.get("code")
            and not result["srt"]["addr"]
        ):
            result["srt"] = {"addr": item["addr"], "code": item["code"]}
    return result


def print_streams(streams: dict) -> None:
    print("开播成功")
    print(f"房间号: {streams['room_id']}")
    print()
    print("RTMP-1")
    print(f"地址: {streams['rtmp1']['addr']}")
    print(f"推流码: {streams['rtmp1']['code']}")
    print()
    print("RTMP-2")
    print(f"地址: {streams['rtmp2']['addr']}")
    print(f"推流码: {streams['rtmp2']['code']}")
    print()
    print("SRT")
    print(f"地址: {streams['srt']['addr']}")
    print(f"推流码: {streams['srt']['code']}")


def main() -> int:
    if len(sys.argv) > 1:
        print(
            "这个脚本不接受参数，直接运行 `python stream.py` 即可",
            file=sys.stderr,
        )
        return 2

    try:
        session = ensure_session()
        result = start_live(session)
        if result.get("code") == 60024:
            print("开播需要人脸认证，请使用 App 扫码完成认证后重新运行脚本")
            print_ascii_qr(result.get("qr", ""))
            return 2

        print_streams(result)
        return 0
    except KeyboardInterrupt:
        print("已取消", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"执行失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
