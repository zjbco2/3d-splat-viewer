#!/usr/bin/env python3
"""splat-viewer 本地服务器

把 ComfyUI 的 output/3d 目录当作模型库对外提供，清单动态生成，
新增 ply 后刷新页面即可看到，不用改任何配置。

用法：
    python serve.py            # 默认 127.0.0.1:8017
    python serve.py 9000       # 指定端口
"""

import json
import mimetypes
import os
import re
import socket
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

# ---- 配置 ----
ROOT = os.path.dirname(os.path.abspath(__file__))
# 项目内 models/ 优先（将来上 git 时模型放这里），找不到再回落到 ComfyUI 输出目录。
# 两个目录都会参与清单扫描，同名文件以项目内的为准。
LOCAL_MODEL_DIR = os.path.join(ROOT, "models")
MODEL_DIR = r"F:\comfyui_official\ComfyUI_windows_portable\ComfyUI\output\3d"
MODEL_EXTS = {".ply", ".spz", ".splat", ".ksplat"}

# --static：清单读硬盘上的 index.json（等价于静态托管的线上行为），而不是每次重扫目录。
# 用途是「部署前预演」——能提前发现忘了跑 build_index.py 的情况。
STATIC_MODE = "--static" in sys.argv
PIC_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

_NUM_RE = re.compile(r"(\d+)(?!.*\d)")


def _trailing_number(filename: str):
    """取文件名里最后一组数字。idol_00030.spz -> 30；idol_00031_.png -> 31。"""
    m = _NUM_RE.search(os.path.splitext(filename)[0])
    return int(m.group(1)) if m else None


def _model_path(filename: str):
    """定位模型文件，返回存在的完整路径，找不到返回 None。
    只在「当前生效目录」里找 —— 与清单保持一致，避免出现
    「列表里看不到、链接却能打开」这种不一致。"""
    filename = os.path.basename(filename)
    base = LOCAL_MODEL_DIR if STATIC_MODE else active_model_dir()
    p = os.path.join(base, filename)
    return p if os.path.isfile(p) else None


def _scan_dir(folder: str):
    """扫一个目录，返回 (模型列表, 图片列表)。目录不存在时返回两个空列表。"""
    models, pics = [], []
    if not os.path.isdir(folder):
        return models, pics
    for name in os.listdir(folder):
        ext = os.path.splitext(name)[1].lower()
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        rec = {"name": name, "size": st.st_size, "mtime": int(st.st_mtime), "ext": ext.lstrip(".")}
        if ext in MODEL_EXTS:
            models.append(rec)
        elif ext in PIC_EXTS:
            pics.append(rec)
    return models, pics


def active_model_dir():
    """决定当前使用哪个模型目录 —— 两者互斥，不混合。

    项目内 models/ 里**有模型文件**时，只读它；
    没有（目录不存在、或存在但为空）才回落到 ComfyUI 输出目录。
    这样上 git 前把模型拷进 models/ 就自动切换，且不会因为建了个空目录而白屏。
    """
    local_models, _ = _scan_dir(LOCAL_MODEL_DIR)
    return LOCAL_MODEL_DIR if local_models else MODEL_DIR


def build_manifest(folder: str):
    """扫指定目录并完成「截图 ↔ 模型」配对，返回清单。

    ComfyUI 的 Save Splat 与 SaveImage 共用计数器但格式不同
    （idol_00021.ply / idol_00022_.png），所以按修改时间就近配对，
    一张截图只归一个模型。

    抽成独立函数是为了让 build_index.py（生成静态 index.json）复用同一套规则，
    避免「本地看到的」和「部署后看到的」对不上。
    """
    models, pics = _scan_dir(folder)

    if not models and not pics:
        return []

    pics.sort(key=lambda x: x["mtime"])
    used = set()

    # 1) 同名配对（理论上不会有，留着兜底）
    pic_by_stem = {}
    for p in pics:
        pic_by_stem[os.path.splitext(p["name"])[0]] = p
    for m in models:
        stem = os.path.splitext(m["name"])[0]
        p = pic_by_stem.get(stem)
        if p is not None and p["name"] not in used:
            m["thumb"] = p["name"]
            used.add(p["name"])
        else:
            m["thumb"] = None

    # 2) 按序号 +1 配对。
    #    Save Splat 先执行、SaveImage 后执行（RenderSplat 依赖前者输出的
    #    camera_info，所以顺序被依赖链锁死），图片编号必然比模型大 1。
    pic_by_num = {}
    for p in pics:
        n = _trailing_number(p["name"])
        if n is not None:
            pic_by_num[n] = p
    for m in models:
        if m["thumb"]:
            continue
        n = _trailing_number(m["name"])
        if n is None:
            continue
        p = pic_by_num.get(n + 1)
        if p is not None and p["name"] not in used:
            m["thumb"] = p["name"]
            used.add(p["name"])

    # 3) 最后按修改时间就近补
    for m in sorted(models, key=lambda x: x["mtime"], reverse=True):
        if m["thumb"]:
            continue
        best, best_gap = None, None
        for p in pics:
            if p["name"] in used:
                continue
            gap = abs(p["mtime"] - m["mtime"])
            if best_gap is None or gap < best_gap:
                best, best_gap = p, gap
        if best is not None and best_gap is not None and best_gap <= 600:
            m["thumb"] = best["name"]
            used.add(best["name"])

    models.sort(key=lambda x: x["mtime"], reverse=True)
    return models


STATIC_MANIFEST = os.path.join(ROOT, "index.json")


def list_models():
    """清单来源分两种：
    - 默认（开发）：每次请求重扫当前生效目录，加了模型刷新就有
    - --static（预演线上）：读硬盘 index.json，与静态托管行为一致
    """
    if STATIC_MODE:
        if not os.path.isfile(STATIC_MANIFEST):
            return []
        try:
            with open(STATIC_MANIFEST, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []
    return build_manifest(active_model_dir())


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/index.json":
            self._send_json(list_models())
            return
        if path.startswith("/models/"):
            self._send_model(path[len("/models/"):])
            return
        super().do_GET()

    def do_HEAD(self):
        path = unquote(urlparse(self.path).path)
        if path == "/index.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            return
        if path.startswith("/models/"):
            fpath = _model_path(path[len("/models/"):])
            if not fpath:
                self.send_error(404, "model not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(os.path.getsize(fpath)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            return
        super().do_HEAD()

    def end_headers(self):
        """本地开发用：页面和清单一律不缓存，避免「改了看不到」。
        模型文件（/models/）不加，它们体积大且不会变，让浏览器缓存反而快。"""
        path = unquote(urlparse(self.path).path)
        if not path.startswith("/models/"):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def _send_json(self, obj):
        body = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_model(self, filename):
        """流式发送模型文件，支持 Range 请求。"""
        path = _model_path(filename)
        if not path:
            self.send_error(404, "model not found")
            return
        filename = os.path.basename(path)

        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if os.path.splitext(filename)[1].lower() in MODEL_EXTS:
            ctype = "application/octet-stream"

        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            try:
                spec = rng[6:].split(",")[0]
                a, _, b = spec.partition("-")
                if a:
                    start = int(a)
                if b:
                    end = int(b)
                start = max(0, start)
                end = min(end, size - 1)
            except ValueError:
                start, end = 0, size - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)

        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, fmt, *args):
        # 只打印非模型请求，避免刷屏
        msg = fmt % args
        if "/models/" not in msg:
            sys.stderr.write("%s\n" % msg)


def main():
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = int(positional[0]) if positional else 8017
    if not os.path.isdir(LOCAL_MODEL_DIR) and not os.path.isdir(MODEL_DIR):
        print(f"[!] 两个模型目录都不存在:\n    项目内: {LOCAL_MODEL_DIR}\n    回落  : {MODEL_DIR}")
        return 1

    # 端口占用检测。
    # Windows 上 HTTPServer 默认 allow_reuse_address=True，第二个进程也能「绑定成功」，
    # 但新连接全被先来的那个接走 —— 表现是「改了代码/加了模型却怎么刷新都不生效」。
    # 所以启动前主动探一下，宁可明确报错也不要静默起一个接不到请求的服务。
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    try:
        busy = probe.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        busy = False
    finally:
        probe.close()
    if busy:
        print(f"[!] 端口 {port} 已被占用，很可能之前开的 splat-viewer 还没关。")
        print("    先结束那个进程，或换端口启动：python serve.py 8018")
        return 1

    count = len(list_models())
    active = active_model_dir()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print("=" * 60)
    print("  splat-viewer" + ("   [静态模式：清单读 index.json]" if STATIC_MODE else ""))
    print(f"  当前使用: {active}")
    if active == LOCAL_MODEL_DIR:
        print(f"  已停用  : {MODEL_DIR}")
        print("            （项目内 models/ 里有模型，两个目录互斥不混合）")
    else:
        print(f"  回落来源: {MODEL_DIR}")
        print("            （项目内 models/ 不存在或为空，暂时读 ComfyUI 输出）")
    print(f"  已发现  : {count} 个模型")
    print(f"  列表页  : {url}")
    print(f"  纯展示页: {url}view.html?model=文件名.spz")
    print("  Ctrl+C 停止")
    print("=" * 60)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
