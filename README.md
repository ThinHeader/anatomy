# 人体解剖学3D交互图谱 | Human Anatomy Explorer

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Data: CC BY-SA 2.1](https://img.shields.io/badge/Data-CC%20BY--SA%202.1-green.svg)](https://creativecommons.org/licenses/by-sa/2.1/jp/)

**[中文](#中文)** | **[English](#english)**

</div>

---

<a name="中文"></a>
## 🇨🇳 中文

基于 **BodyParts3D/ISA** 真实MRI扫描数据的3D人体解剖可视化应用，支持11大系统交互式浏览。本项目采用模型库中的 **ISA (Intuitive Surgical Anatomy)** 分类体系进行组织。

### ✨ 功能特点

- ✅ **真实人体模型** - 基于2mm MRI扫描的医学级数据
- ✅ **11大解剖系统** - 骨骼、肌肉、心血管、神经、消化、呼吸、泌尿、生殖、内分泌、淋巴、皮肤
- ✅ **双语标注** - 中文 + 英文解剖学术语
- ✅ **全局搜索** - 一键搜索所有系统，自动打开对应图层
- ✅ **智能高亮** - 选中模型高亮显示，其他模型自动半透明
- ✅ **图层控制** - 独立开关各系统，自由组合显示
- ✅ **双向交互** - 点击列表项或3D模型相互联动
- ✅ **平滑动画** - 相机自动聚焦到选中部位

### 🚀 快速开始

**在线访问**
🌐 **GitHub Pages**: https://jixiangying.github.io/anatomy/

**本地运行**
```bash
git clone https://github.com/jixiangying/anatomy.git
cd anatomy
npm start                 # 等价于 node server.js，默认 3000 端口
# 浏览器访问 http://localhost:3000
```

> 也可以用 `python3 -m http.server 3000`，但不带 gzip 与缓存，首次加载会明显更慢。

**重新生成模型加速包**（改了 `isa_BP3D_4.0_obj_99/` 里的模型后才需要跑）
```bash
python tools/build_models.py   # obj -> models/<system>.bin
```

### ⚡ 性能优化

原始实现是「一个模型一个 `.obj` 请求」：默认加载骨骼+肌肉共 **667 个请求 / 226MB 文本**，浏览器要逐个下载并做文本解析，实测 4 分钟还没加载完。

现在改为**按系统打包的量化二进制模型库**：

| 优化项 | 做法 | 效果 |
|------|------|------|
| 请求数 | 2234 个 `.obj` → 11 个 `.bin`，一次请求加载整个系统 | 默认加载 667 → **2 个请求** |
| 数据体积 | 顶点坐标 int16 量化 + 法线 int8 量化 + 索引 uint16/uint32 | 494.7MB → **82.9MB**（6.0 倍） |
| 解析开销 | 跳过 OBJ 文本解析，直接建 `BufferGeometry` | 668 个模型构建耗时 **97ms** |
| 传输 | 构建时预压缩 `.bin.gz`，服务端直接下发 | 默认加载 38.5MB → **27MB** |
| 缓存 | `/models` `/js` 强缓存 + ETag/304 | 刷新基本 0 下载 |
| 缓存失效 | `manifest.json` 记录每个包的内容哈希，请求带 `?v=<hash>` | 重建模型后自动换 URL，不会读到旧包 |
| 加载体验 | 分片构建 + 骨骼先就绪即撤遮罩 | 首屏约 **0.9s**，全部就绪约 **1.5s** |
| 渲染批次 | 同系统部位合并进少量大几何体（按身体竖向分块），顶点带 `aId` 部位编号 | draw call 667 → **10**（11 个系统全开 47） |
| 高亮/变暗 | 着色器比对 `aId` 与 `uHighlightId`，不再逐 mesh 换材质 | 切换耗时 **0.17ms**（原遍历 667 个 mesh） |
| 拾取 | chunk 包围盒 → 部位包围盒 → 三角形三级筛选 | 悬停拾取 **4ms**，与场景复杂度无关 |

> 实测环境：Intel HD Graphics 520 / Chromium。原生 GPU 机器会更快。
> 精度：量化后包围盒误差 < 0.1mm，肉眼无差别。
> 帧率：默认骨骼+肌肉约 55fps（原 667 个独立 mesh 时约 37fps）；全系统 6.7M 三角形约 31fps，瓶颈在核显的顶点/填充率，不在 draw call。

加载逻辑带降级：`models/<system>.bin` 不存在时自动回退到逐个 `.obj` 加载，因此只保留原始模型目录也能跑。

### 🎮 使用说明

| 操作 | 功能 |
|------|------|
| 左键拖动 | 旋转视角 |
| 右键拖动 | 平移视角 |
| 滚轮 | 缩放 |
| 搜索框 | 全局搜索所有系统的部位 |
| 点击左侧列表 | 高亮3D模型并聚焦 |
| 点击3D模型 | 自动高亮并滚动左侧列表 |
| 点击空白处 | 取消选择，恢复全不透明 |
| 右侧图层控制 | 开关各系统显示 |

### ⚠️ 数据说明

**AI 辅助分类与翻译**

> ⚠️ **注意**：本项目的解剖学分类和中文翻译均由 **AI 基于 BodyParts3D 官网 ISA 相关说明文档** 自动生成，可能存在以下问题：
> - **部件名称提取欠优化**：由于一个模型对应多个解剖学标签（FMA），自动提取的英文名可能不是最通用的术语。
> - **解剖学术语翻译不够精准**：个别生僻术语可能不符合中文医学惯例。
> - **模型分类归属可能存在偏差**。
>
> 🔍 **已知问题**：由于原始 BodyParts3D 模型库的数据组织原因，存在个别解剖实体重复的模型文件（如 **FJ2440** 与 **FJ2769** 均为环状软骨）。
>
> **如需更正**：请直接修改 `data/anatomy_data_simple_refined.json` 文件中的对应字段。
> ```json
> {
>   "id": "FJ3152",
>   "name": "右髋骨 | right hip bone",
>   "system": "骨骼系统",
>   "nameEn": "right hip bone",
>   "nameCn": "右髋骨",
>   "systemEn": "Skeletal System"
> }
> ```
> 欢迎提交 Pull Request 帮助改进数据质量！

### 🏥 数据来源

- **项目**: BodyParts3D / ISA (Intuitive Surgical Anatomy)
- **版本**: Release 4.0 ([2021-06-08 16:43](https://dbarchive.biosciencedbc.jp/data/bodyparts3d/))
- **机构**: 日本东京大学生命科学数据库中心
- **分类体系**: **ISA (Intuitive Surgical Anatomy)**
- **许可**: CC BY-SA 2.1 Japan
- **模型数**: 2,234个OBJ文件

---

<a name="english"></a>
## 🇬🇧 English

A 3D human anatomy visualization application based on **BodyParts3D/ISA** real MRI scan data, supporting interactive browsing of 11 major anatomical systems. This project utilizes the **ISA (Intuitive Surgical Anatomy)** classification system.

### ✨ Features

- ✅ **Real Human Models** - Medical-grade data based on 2mm MRI scans
- ✅ **11 Anatomical Systems** - Skeletal, Muscular, Cardiovascular, Nervous, Digestive, Respiratory, Urinary, Reproductive, Endocrine, Lymphatic, Integumentary
- ✅ **Bilingual Labels** - Chinese + English anatomical terminology
- ✅ **Global Search** - Search across all systems with auto-layer activation
- ✅ **Smart Highlight** - Highlight selected model, others become semi-transparent
- ✅ **Layer Control** - Toggle individual systems, freely combine displays
- ✅ **Bidirectional Interaction** - Click list items or 3D models to sync with each other
- ✅ **Smooth Animation** - Camera automatically focuses on selected parts

### 🚀 Quick Start

**Online Access**
🌐 **GitHub Pages**: https://jixiangying.github.io/anatomy/

**Local Run**
```bash
git clone https://github.com/jixiangying/anatomy.git
cd anatomy
npm start                 # same as `node server.js`, port 3000
# Open http://localhost:3000
```

> `python3 -m http.server 3000` also works, but ships without gzip/caching and loads noticeably slower.

**Rebuild the model bundles** (only needed after changing files in `isa_BP3D_4.0_obj_99/`)
```bash
python tools/build_models.py   # obj -> models/<system>.bin
```

### ⚡ Performance

The original build requested one `.obj` per part: **667 requests / 226MB of text** for the default skeletal+muscular view, which took over 4 minutes to load.

Models are now shipped as **per-system quantized binary bundles**:

| Optimization | Approach | Result |
|---|---|---|
| Requests | 2234 `.obj` → 11 `.bin`, one request per system | 667 → **2 requests** |
| Payload | int16 positions + int8 normals + uint16/uint32 indices | 494.7MB → **82.9MB** (6.0x) |
| Parsing | no OBJ text parsing, build `BufferGeometry` directly | 668 geometries in **97ms** |
| Transfer | `.bin.gz` pre-compressed at build time | 38.5MB → **27MB** |
| Caching | immutable cache + ETag/304 for `/models` `/js` | reload ≈ 0 download |
| UX | chunked build, overlay removed once skeleton is ready | first paint **2.2s**, fully loaded **3.2s** |

> Measured on Intel HD Graphics 520 / Chromium; faster on a discrete GPU.
> Quantization error stays under 0.1mm — visually indistinguishable.

Loading degrades gracefully: if `models/<system>.bin` is missing it falls back to per-`.obj` loading.

### 🎮 Usage

| Action | Function |
|--------|----------|
| Left drag | Rotate view |
| Right drag | Pan view |
| Scroll | Zoom |
| Search box | Global search for all system parts |
| Click left list | Highlight 3D model and focus |
| Click 3D model | Auto-highlight and scroll left list |
| Click blank area | Deselect, restore full opacity |
| Right control | Toggle system visibility |

### ⚠️ Data Notice

**AI-Assisted Processing**

> ⚠️ **Note**: The anatomical classifications and translations in this project were **automatically generated by AI based on BodyParts3D ISA documentation** and may contain:
> - **Under-optimized Name Extraction**: Since one model may correspond to multiple anatomical labels (FMA), the automatically extracted English names might not be the most common clinical terms.
> - **Imprecise anatomical terminology translations**.
> - **Potential deviations in model classification**.
>
> 🔍 **Known Issues**: Due to the data organization of the original BodyParts3D library, there are a few duplicate model files for the same anatomical entity (e.g., **FJ2440** and **FJ2769** are both cricoid cartilage).
>
> **To Correct**: Please modify the corresponding fields in `data/anatomy_data_simple_refined.json`.
> ```json
> {
>   "id": "FJ3152",
>   "name": "右髋骨 | right hip bone",
>   "system": "骨骼系统",
>   "nameEn": "right hip bone",
>   "nameCn": "右髋骨",
>   "systemEn": "Skeletal System"
> }
> ```
> Pull Requests are welcome to help improve data quality!

### 🏥 Data Source

- **Project**: BodyParts3D / ISA (Intuitive Surgical Anatomy)
- **Version**: Release 4.0 ([2021-06-08 16:43](https://dbarchive.biosciencedbc.jp/data/bodyparts3d/))
- **Organization**: Database Center for Life Science (DBCLS), Japan
- **Classification**: **ISA (Intuitive Surgical Anatomy)**
- **License**: CC BY-SA 2.1 Japan
- **Count**: 2,234 OBJ files

---

<div align="center">

Created with ❤️ for anatomy education
**人体解剖学教育 · Human Anatomy Education**

</div>
