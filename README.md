# splat-viewer

看 3D 高斯点云（`.spz` / `.ply` / `.splat`）的本地页面，纯前端，无构建步骤。

- **列表页 `index.html`** —— 左侧挑模型，右侧看，带底色 / 上方向 / 网格 / 重置视角
- **纯展示页 `view.html`** —— 整页只有模型，纯白底、无网格、无 UI，可用链接指定某个模型

---

## 本地怎么看

双击 **`启动.bat`**（或 `python serve.py`），默认 `http://127.0.0.1:8017/`。
清单每次请求都重扫目录，**加了模型刷新就有**，不用跑任何命令。

模型从哪读（两者互斥，不混合）：

```
models/ 里有模型文件  →  只读 models/
models/ 不存在或是空的 →  回落到 ComfyUI 的 output\3d
```

启动时会打印当前用的是哪个目录。

> **端口被占会直接报错退出**，不会默默起一个接不到请求的服务。
> 换端口：`python serve.py 8018`
>
> 部署前想预演线上行为（清单读 `index.json` 而不是扫目录）：
> `python serve.py --static`

### 为什么不能直接双击 index.html

**不行，必须走 http。** 浏览器对 `file://` 有三层限制，这个页面踩中两条：

| 限制 | 本页是否踩中 |
|---|---|
| ES module 受同源策略约束（`file://` 的 origin 是 `null`，直接拒绝加载） | ✅ 页面用 `<script type="module">` |
| `fetch` / `XHR` 不能读本地文件 | ✅ 读 `index.json` 和 `.spz` 都走 fetch |

所以双击只会得到白屏 + 控制台一串 CORS 报错。

`chrome.exe --allow-file-access-from-files` 理论上能绕过，但那是关掉浏览器一层安全机制，不建议为看模型付这个代价。
**任何静态服务器都行**，本项目自带两个 bat 就是干这个的。

---

## 纯展示页用法

```
view.html?model=idol_00055.spz            基础
view.html?model=xxx.spz&yaw=90            个别模型朝向不对，补转 90°
view.html?model=xxx.spz&up=0,0,1          个别模型是 Z 向上
```

列表页选中模型后点顶栏 **「复制直链」**，会自动生成完整链接。

---

## 加模型

1. 把 `.spz` / `.ply` 和同名截图放进 `models/`
2. 本地：刷新页面即可（serve.py 每次请求重扫）
3. **要提交 git：先跑一次 `python build_index.py`**（见下）

截图和模型的配对规则：先找同名，再找「序号 +1」（ComfyUI 的 Save Splat 先跑、SaveImage 后跑，编号必然差 1），最后按修改时间就近补（10 分钟内）。

---

## 部署到静态托管（GitHub Pages / Vercel / Netlify）

静态托管**没有 Python**，所以两件事必须变成静态文件：

| 运行时做的 | 静态版的替代 |
|---|---|
| `/models/xxx` 映射到外部目录 | **不需要** —— 模型就在项目内 `models/`，天然可访问 |
| `/index.json` 动态扫描 | **`build_index.py` 提前生成** |

### 步骤

1. 确认模型都在 `models/` 里（托管只认项目内目录，不读 ComfyUI）
2. 生成清单：
   ```bash
   python build_index.py
   ```
   加模型之后**每次都要重跑**，然后把 `index.json` 一起提交。
3. 全部推上去：
   ```bash
   git add .
   git commit -m "update models"
   git push
   ```
4. 托管平台选「静态站点」，根目录填这个文件夹，**不需要构建命令**

所有路径都是相对的（`models/`、`index.json`），所以放在
`https://用户名.github.io/splat-viewer/` 这种子路径下也能正常工作。

提交前想确认清单是不是漏了更新：

```bash
python build_index.py --check     # 有差异会提示，退出码 2
```

### 可选：让 Actions 自动更新清单

不想每次手动跑，就在仓库里建 `.github/workflows/build-index.yml`：

```yaml
name: build index
on:
  push:
    paths:
      - 'models/**'
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.x'
      - run: python build_index.py
      - name: commit if changed
        run: |
          if git diff --quiet index.json; then exit 0; fi
          git config user.name  "github-actions"
          git config user.email "github-actions@users.noreply.github.com"
          git add index.json
          git commit -m "chore: rebuild index.json"
          git push
```

---

## 文件说明

| 文件 | 作用 | 静态托管需要吗 |
|---|---|---|
| `index.html` | 列表页 + 查看器 | ✅ |
| `view.html` | 纯展示页 | ✅ |
| `index.json` | 模型清单（`build_index.py` 生成） | ✅ |
| `models/` | 模型与截图 | ✅ |
| `serve.py` | 本地开发服务器 | ❌ |
| `build_index.py` | 生成静态清单 | ❌（本地工具） |
| `启动.bat` | 双击起服务 | ❌ |

依赖全部走 CDN（three.js 0.160.0 + gaussian-splats-3d 0.4.7），静态托管直接可用。

---

## 注意

- **模型文件不小**，单个 `.spz` 已经 3MB 上下。仓库攒多了会变重，可以考虑只挑代表性的进版本库，或者改用 Git LFS。
- 两个页面的取景常量必须一致（`FIT_SIZE` / `HOME_POS`），否则同一个模型在两处的大小和角度会不一样。
