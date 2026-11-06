#!/usr/bin/env python3
"""生成静态 index.json —— 给 git / 静态托管用。

本地开发不需要它（serve.py 每次请求都会动态扫目录）。
但静态托管没有 Python 运行时，清单必须是硬盘上的一个文件。

用法：
    python build_index.py          # 扫 models/，生成 index.json
    python build_index.py --check  # 只报告差异，不写文件

加完模型、提交 git 之前跑一次即可。
"""

import json
import os
import sys

import serve

OUT_PATH = os.path.join(serve.ROOT, "index.json")


def current_text(models):
    return json.dumps(models, ensure_ascii=False, indent=1) + "\n"


def main():
    check_only = "--check" in sys.argv

    if not os.path.isdir(serve.LOCAL_MODEL_DIR):
        print(f"[!] 项目内没有 models/ 目录：{serve.LOCAL_MODEL_DIR}")
        print("    静态托管的清单只能来自项目内 models/，请先把模型放进去。")
        return 1

    models = serve.build_manifest(serve.LOCAL_MODEL_DIR)
    if not models:
        print(f"[!] models/ 里没有模型文件。支持的扩展名："
              f"{' '.join(sorted(serve.MODEL_EXTS))}")
        return 1

    new_text = current_text(models)
    old_text = None
    if os.path.isfile(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            old_text = f.read()

    with_thumb = sum(1 for m in models if m.get("thumb"))
    if check_only:
        if old_text == new_text:
            print(f"[OK] index.json 是最新的（{len(models)} 个模型）")
            return 0
        print(f"[!] index.json 与 models/ 不一致（应有 {len(models)} 个模型）")
        print("    跑一次 python build_index.py 更新")
        return 2

    if old_text == new_text:
        print(f"[OK] 没有变化，index.json 已是最新（{len(models)} 个模型）")
        return 0

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(new_text)

    print(f"[OK] 已写入 {OUT_PATH}")
    print(f"     模型 {len(models)} 个，其中 {with_thumb} 个有缩略图，"
          f"{len(models) - with_thumb} 个没有")
    return 0


if __name__ == "__main__":
    sys.exit(main())
