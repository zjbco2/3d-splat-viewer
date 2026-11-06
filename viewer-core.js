/* 主页（index.html）与纯展示页（view.html）共用的 3D 逻辑。
 *
 * 为什么要有这个文件：
 * 之前两个页面各写一套 3D 代码，结果反复出现「改了主页、忘了展示页」——
 * 平移的接管逻辑只加在主页，展示页拖动就会绕空点转、还会透视变形。
 * 现在取景常量、模型适配、平移都收在这里，改一处两边同时生效。
 *
 * 各页面自己保留的只有：DOM、样式、自己的交互（列表 / URL 参数）。
 */

import * as THREE from 'three';
import * as GaussianSplats3D from '@mkkellogg/gaussian-splats-3d';

/* ---- 取景常量 ----
   两个页面必须用同一套值，否则同一个模型在两边的大小、角度会不一样。
   改 FIT_SIZE 就得同步考虑 HOME_POS 的距离，否则画面大小会跳。 */
export const FIT_SIZE = 4.2;            // 模型归一化后的最长边
export const HOME_POS  = [7, -2.5, 0];  // 默认机位
export const HOME_UP   = [0, -1, 0];    // 默认上方向（3DGS 常规）

/** 创建查看器。只传挂载点也能跑，其余走默认值。
 *
 * 为什么要自己建 renderer：
 * 库默认用 preserveDrawingBuffer = false 建 WebGL 上下文，那种情况下
 * 截图（drawImage / toDataURL）经常只能拿到空白。传入外部 renderer 时
 * 库会跳过自己的初始化，所以下面几件事要我们自己接手：
 *   - 建 canvas 并挂到容器
 *   - 设像素比 / 尺寸
 *   - 容器尺寸变化时同步尺寸（库不会再管）
 * 相机宽高比由库的渲染循环每帧自己校正，不用我们操心。
 */
export function createViewer(host, opts = {}) {
  const dpr = window.devicePixelRatio || 1;

  const renderer = new THREE.WebGLRenderer({
    antialias: !!opts.antialiased,
    precision: 'highp',
    preserveDrawingBuffer: true,   // ← 截图能读到内容的关键
    alpha: true,
  });
  renderer.setPixelRatio(dpr);
  renderer.autoClear = true;
  renderer.setClearColor(new THREE.Color(0x000000), 0.0);
  renderer.setSize(host.clientWidth || 1, host.clientHeight || 1);
  host.appendChild(renderer.domElement);

  const viewer = new GaussianSplats3D.Viewer({
    rootElement: host,
    renderer,
    cameraUp: opts.cameraUp || HOME_UP,
    initialCameraPosition: opts.position || HOME_POS,
    initialCameraLookAt: opts.lookAt || [0, 0, 0],
    sharedMemoryForWorkers: false,
    gpuAcceleratedSort: false,
    useBuiltInControls: true,
    showLoadingUI: false,
    antialiased: !!opts.antialiased,
  });

  // 库不接管尺寸了，自己跟
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => {
      renderer.setSize(host.clientWidth || 1, host.clientHeight || 1);
      if (typeof viewer.forceRenderNextFrame === 'function') viewer.forceRenderNextFrame();
    });
    ro.observe(host);
  }

  viewer.__renderer = renderer;   // 截图时要用
  return viewer;
}

/**
 * 把模型包围盒中心移到原点、最长边缩放到 FIT_SIZE，再按 yaw 补转。
 * 这样不管原始坐标偏移多少、尺度多大，都能落进默认视野。
 *
 * 注意：算包围盒前必须先清零 scale/position/rotation，
 * 否则第二次调用用的是已缩放过的大小，结果等于「重置没反应」。
 *
 * @returns {boolean} 是否成功（包围盒为空时返回 false）
 */
export function fitMesh(mesh, yawDeg = 0) {
  if (!mesh) return false;

  mesh.scale.setScalar(1);
  mesh.position.set(0, 0, 0);
  mesh.rotation.y = 0;
  mesh.updateMatrixWorld(true);

  let box;
  try {
    box = mesh.computeBoundingBox(true);
  } catch (e) {
    return false;
  }
  if (!box || box.isEmpty()) return false;

  const c  = box.getCenter(new THREE.Vector3());
  const sz = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(sz.x, sz.y, sz.z);
  if (!isFinite(maxDim) || maxDim <= 0) return false;

  const s = FIT_SIZE / maxDim;
  mesh.scale.setScalar(s);
  mesh.position.set(-c.x * s, -c.y * s, -c.z * s);
  mesh.rotation.y = yawDeg * Math.PI / 180;
  mesh.updateMatrixWorld(true);
  return true;
}

/**
 * 画面内平移控制器。
 *
 * 原理解释（以后别再改错方向）：
 * 控件库的旋转永远绕「画面中心那个点」转，那个点就是 camera 看的 target。
 * 所以平移如果去动相机（移动 camera + target），target 就离开了模型，
 * 旋转变成绕空点画圈，同时相机位置变化还会带来透视变形。
 *
 * 这里不这么做：相机位置和 target 都不动，只给相机设「取景偏移」
 * （camera.setViewOffset，相当于镜头平移）—— 透视和朝向全不变，
 * 画面整体平移，模型看起来换了位置，而旋转缩放仍绕模型自身；
 * 画布也始终铺满可视区，模型不会被画布边缘切成直角。
 *
 * 用法：
 *   const pan = createPanController(stageEl, () => viewer);
 *   pan.reset()                 // 重置视角时
 *   pan.setFromPercent(x, y)    // 还原分享链接里的位置
 *   pan.getPercent()            // 生成分享链接时
 *   pan.apply()                 // 容器尺寸变化后重新套用
 */
export function createPanController(stageEl, getViewer) {
  let panX = 0;
  let panY = 0;
  let panning = false;
  let last = null;

  const clamp = (v, size) => Math.max(-size * 0.8, Math.min(size * 0.8, v));

  function apply() {
    const viewer = getViewer();
    const cam = viewer && viewer.camera;
    if (!cam || typeof cam.setViewOffset !== 'function') return;

    const w = stageEl.clientWidth  || 1;
    const h = stageEl.clientHeight || 1;

    if (!panX && !panY) {
      cam.clearViewOffset();                    // 内部会重算投影矩阵
    } else {
      cam.setViewOffset(w, h, -panX, -panY, w, h);
    }
    if (typeof viewer.forceRenderNextFrame === 'function') {
      viewer.forceRenderNextFrame();
    }
  }

  function move(dxPx, dyPx) {
    panX = clamp(panX + dxPx, stageEl.clientWidth  || 1);
    panY = clamp(panY + dyPx, stageEl.clientHeight || 1);
    apply();
  }

  // 不拦的话，右键一拖就弹浏览器菜单，拖动直接被打断
  stageEl.addEventListener('contextmenu', e => e.preventDefault());

  // 捕获阶段接管，抢在 canvas 上的 OrbitControls 之前
  stageEl.addEventListener('pointerdown', e => {
    const isPan = (e.button === 2) || (e.button === 0 && e.shiftKey);
    if (!isPan || !getViewer()) return;
    e.preventDefault();
    e.stopPropagation();                        // 别让 canvas 自己再平移一遍
    panning = true;
    last = { x: e.clientX, y: e.clientY };
    try { stageEl.setPointerCapture(e.pointerId); } catch (_) {}
    stageEl.style.cursor = 'grabbing';
  }, true);

  stageEl.addEventListener('pointermove', e => {
    if (!panning) return;
    e.preventDefault();
    e.stopPropagation();
    const dx = e.clientX - last.x;
    const dy = e.clientY - last.y;
    last = { x: e.clientX, y: e.clientY };
    move(dx, dy);
  }, true);

  function end(e) {
    if (!panning) return;
    e.stopPropagation();
    panning = false;
    last = null;
    stageEl.style.cursor = '';
  }
  stageEl.addEventListener('pointerup', end, true);
  stageEl.addEventListener('pointercancel', end, true);

  return {
    /** 归零 */
    reset() { panX = 0; panY = 0; apply(); },

    /** 按画面百分比设置位置（分享链接用） */
    setFromPercent(px, py) {
      panX = (px || 0) / 100 * (stageEl.clientWidth  || 1);
      panY = (py || 0) / 100 * (stageEl.clientHeight || 1);
      apply();
    },

    /** 读当前位置，换算成画面百分比（分享链接用） */
    getPercent() {
      return {
        x: panX / (stageEl.clientWidth  || 1) * 100,
        y: panY / (stageEl.clientHeight || 1) * 100,
      };
    },

    /** 容器尺寸变了要重新套用（库会重算投影矩阵把偏移冲掉） */
    apply,
  };
}
