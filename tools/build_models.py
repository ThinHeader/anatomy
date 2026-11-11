#!/usr/bin/env python3
"""
把 isa_BP3D_4.0_obj_99/*.obj 打包成按解剖系统分文件的量化二进制模型库。

产物: models/<system>.bin  (单次请求加载整个系统)
      models/manifest.json (系统 -> 文件/字节数/模型数)

格式 ANTB v1 (全部小端):
  magic  : 4 bytes  b'ANTB'
  version: uint32   = 1
  jsonLen: uint32
  json   : utf-8 (模型元数据数组)
  之后是 4 字节对齐的数据区:
     positions : int16   xyz  (量化, p = center + q * scale)
     normals   : int8    xyz  (n * 127)
     indices   : uint32 / uint16  (vCount <= 65535 时用 uint16)

用法: python tools/build_models.py
"""
import datetime
import gzip
import hashlib
import json
import os
import struct
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBJ_DIR = os.path.join(ROOT, "isa_BP3D_4.0_obj_99")
DATA_JSON = os.path.join(ROOT, "data", "anatomy_data_simple_refined.json")
OUT_DIR = os.path.join(ROOT, "models")

PAD = 4


def parse_obj(path):
    """返回 (verts[N,3] float32, norms[N,3] float32 或 None, faces[M,3] int32)"""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    v_raw, vn_raw, f_raw = [], [], []
    for line in text.splitlines():
        if not line or line[0] not in "vf":
            continue
        if line[0] == "v" and line[1] == " ":
            v_raw.append(line[2:])
        elif line[0] == "v" and line[1] == "n":
            vn_raw.append(line[3:])
        elif line[0] == "f" and line[1] == " ":
            f_raw.append(line[2:])
        elif line[0] == "f" and line[1] == "a":  # 非三角面兜底
            f_raw.append(line[2:])

    if not v_raw or not f_raw:
        return None

    verts = np.fromstring(" ".join(v_raw).replace("\n", " "), sep=" ", dtype=np.float64)
    verts = verts[: (len(verts) // 3) * 3].reshape(-1, 3).astype(np.float32)

    norms = None
    if vn_raw:
        arr = np.fromstring(" ".join(vn_raw), sep=" ", dtype=np.float64)
        arr = arr[: (len(arr) // 3) * 3]
        if arr.size == verts.size:
            norms = arr.reshape(-1, 3).astype(np.float32)

    # 三角化: 每行只取顶点索引 (a//b -> a), 多边形用扇形切分
    tri = []
    for row in f_raw:
        idx = []
        for tok in row.split():
            s = tok.split("/", 1)[0]
            if s:
                idx.append(int(s) - 1)
        idx = [i for i in idx if i >= 0]
        for k in range(1, len(idx) - 1):
            tri.append((idx[0], idx[k], idx[k + 1]))
    if not tri:
        return None
    faces = np.asarray(tri, dtype=np.int32)

    # 丢弃越界索引
    valid = faces < len(verts)
    if not valid.all():
        keep = valid.all(axis=1)
        faces = faces[keep]
        if not len(faces):
            return None

    return verts, norms, faces


def quantize(verts):
    lo = verts.min(axis=0)
    hi = verts.max(axis=0)
    center = (lo + hi) / 2.0
    scale = np.where((hi - lo) > 1e-6, (hi - lo) / 65534.0, 1.0).astype(np.float32)
    q = np.rint((verts - center) / scale)
    q = np.clip(q, -32767, 32767).astype(np.int16)
    return q, center.astype(np.float32), scale


def build_system_bytes(system, models):
    pos_bytes, nrm_bytes, idx_bytes, meta = [], [], [], []
    pos_off = nrm_off = idx_off = 0  # 各段内的字节偏移
    skipped = 0

    for m in models:
        mid = m["id"]
        path = os.path.join(OBJ_DIR, mid + ".obj")
        if not os.path.exists(path):
            skipped += 1
            continue
        parsed = parse_obj(path)
        if parsed is None:
            skipped += 1
            continue
        verts, norms, faces = parsed
        count = len(verts)

        q, center, scale = quantize(verts)
        pb = q.tobytes()
        pos_bytes.append(pb)

        if norms is not None:
            n8 = np.clip(np.rint(norms * 127.0), -127, 127).astype(np.int8)
        else:
            n8 = np.zeros((count, 3), dtype=np.int8)
        nb = n8.tobytes()
        nrm_bytes.append(nb)

        if count <= 65535:
            ib = faces.astype(np.uint16).tobytes()
            itype = 2
        else:
            ib = faces.astype(np.uint32).tobytes()
            itype = 4
        # 索引段按 4 字节对齐，保证 JS 里 Uint32Array 视图可以直接建立
        pad = (-len(ib)) % PAD
        if pad:
            ib += b"\x00" * pad
        idx_bytes.append(ib)

        meta.append({
            "id": mid,
            "vCount": count,
            "iCount": int(faces.size),
            "pOff": pos_off,
            "nOff": nrm_off,
            "iOff": idx_off,
            "iType": itype,
            "center": [round(float(x), 4) for x in center],
            "scale": [round(float(x), 8) for x in scale],
        })
        pos_off += len(pb)
        nrm_off += len(nb)
        idx_off += len(ib)

    if not meta:
        return None, 0, skipped

    # 偏移统一改成「相对于数据区起点」的绝对偏移（三段依次排布）
    # 注意：法线段长度可能是奇数，索引段必须 4 字节对齐，否则 JS 无法直接建立 TypedArray 视图
    pos_total = sum(len(b) for b in pos_bytes)
    nrm_total = sum(len(b) for b in nrm_bytes)
    idx_start = ((pos_total + nrm_total + PAD - 1) // PAD) * PAD
    po, no, io = 0, pos_total, idx_start
    for i, mm in enumerate(meta):
        mm["pOff"] = po
        po += len(pos_bytes[i])
        mm["nOff"] = no
        no += len(nrm_bytes[i])
        mm["iOff"] = io
        io += len(idx_bytes[i])

    section = (b"".join(pos_bytes) + b"".join(nrm_bytes)
               + b"\x00" * (idx_start - pos_total - nrm_total)
               + b"".join(idx_bytes))
    return meta, section, skipped


def main():
    with open(DATA_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {}
    grand_in = grand_out = 0

    for system, models in data.items():
        if not models:
            continue
        meta, section, skipped = build_system_bytes(system, models)
        if meta is None:
            continue

        js = json.dumps(meta, separators=(",", ":")).encode("utf-8")
        header = b"ANTB" + struct.pack("<II", 1, len(js)) + js
        pad = (-len(header)) % PAD
        header += b"\x00" * pad
        out = header + section

        path = os.path.join(OUT_DIR, system + ".bin")
        # 原子写入：先写临时文件再改名，避免浏览器/服务器读到写了一半的包
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(out)
        os.replace(tmp, path)

        # 预压缩：服务器直接下发 .gz，避免首次请求时现压大文件
        tmpgz = path + ".gz.tmp"
        with open(tmpgz, "wb") as f:
            f.write(gzip.compress(out, 9))
        os.replace(tmpgz, path + ".gz")

        # 内容哈希用于 URL 版本号，重建后自动击穿浏览器缓存
        digest = hashlib.sha256(out).hexdigest()[:12]

        src = sum(
            os.path.getsize(os.path.join(OBJ_DIR, m["id"] + ".obj"))
            for m in models
            if os.path.exists(os.path.join(OBJ_DIR, m["id"] + ".obj"))
        )
        grand_in += src
        grand_out += len(out)
        manifest[system] = {
            "file": system + ".bin",
            "bytes": len(out),
            "models": len(meta),
            "hash": digest,
        }
        print(f"{system:15s} {len(meta):5d} models  {src/1e6:7.1f} MB -> {len(out)/1e6:6.1f} MB"
              + (f"  (skip {skipped})" if skipped else ""))

    manifest["_build"] = {
        "version": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "generator": "tools/build_models.py",
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\nTOTAL {grand_in/1e6:.1f} MB -> {grand_out/1e6:.1f} MB "
          f"({grand_in/max(grand_out,1):.1f}x 压缩)")

    verify_all(manifest)


def read_bin(path):
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:4] != b"ANTB":
        raise ValueError("bad magic: " + path)
    version, json_len = struct.unpack_from("<II", buf, 4)
    meta = json.loads(buf[12:12 + json_len].decode("utf-8"))
    data_start = (12 + json_len + 3) & ~3
    return buf, meta, data_start


def obj_bounds(path):
    """从 obj 注释里读 Bounds(mm): (x,y,z)-(x,y,z)"""
    import re
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for _ in range(20):
            line = f.readline()
            if not line:
                break
            if line.startswith("# Bounds(mm):"):
                nums = re.findall(r"-?\d+\.?\d*", line)
                return np.array([float(x) for x in nums[:6]])
    return None


def verify_all(manifest, sample=4):
    """解码 bin 并与原 obj 的包围盒比对，确认偏移/量化正确"""
    print("\n校验 (解码 bin vs obj 包围盒)：")
    worst_all = 0.0
    for system, info in manifest.items():
        if system.startswith("_"):
            continue
        path = os.path.join(OUT_DIR, info["file"])
        buf, meta, data_start = read_bin(path)
        step = max(1, len(meta) // sample)
        worst = 0.0
        for m in meta[::step][:sample]:
            # 对齐检查：JS 里要直接在这些偏移上建 TypedArray 视图
            if (data_start + m["iOff"]) % 4 != 0:
                print(f"  ! {system}/{m['id']} 索引偏移未 4 字节对齐")
            if (data_start + m["pOff"]) % 2 != 0:
                print(f"  ! {system}/{m['id']} 顶点偏移未 2 字节对齐")
            q = np.frombuffer(buf, dtype="<i2", count=m["vCount"] * 3,
                              offset=data_start + m["pOff"]).reshape(-1, 3)
            pos = np.array(m["center"], dtype=np.float32) + q * np.array(m["scale"], dtype=np.float32)
            ref = obj_bounds(os.path.join(OBJ_DIR, m["id"] + ".obj"))
            if ref is not None:
                worst = max(worst, float(np.abs(pos.min(0) - ref[:3]).max()),
                            float(np.abs(pos.max(0) - ref[3:]).max()))
            n8 = np.frombuffer(buf, dtype=np.int8, count=m["vCount"] * 3,
                               offset=data_start + m["nOff"])
            if not np.any(n8):
                print(f"  ! {system}/{m['id']} 法线全为 0")
            idx = np.frombuffer(buf, dtype=("<u2" if m["iType"] == 2 else "<u4"),
                                count=m["iCount"], offset=data_start + m["iOff"])
            if idx.size and int(idx.max()) >= m["vCount"]:
                print(f"  ! {system}/{m['id']} 索引越界 {int(idx.max())} >= {m['vCount']}")
        worst_all = max(worst_all, worst)
        flag = "OK" if worst < 1.0 else "!! 偏差过大"
        print(f"  {system:15s} 最大包围盒偏差 {worst:6.3f} mm  {flag}")
    print(f"\n总体最大偏差 {worst_all:.3f} mm（量化误差应 < 0.1 mm）")


if __name__ == "__main__":
    main()
