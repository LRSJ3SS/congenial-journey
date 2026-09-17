# UABE Web - Python core (runs in browser via Pyodide, static-hostable on GitHub Pages)
import struct, json, base64, io
try:
    import lzma as _lzma
    _HAS_LZMA = True
except Exception:
    _lzma = None
    _HAS_LZMA = False

# ---------- helpers ----------
def u32be(b, o): return struct.unpack_from(">I", b, o)[0]
def i32be(b, o): return struct.unpack_from(">i", b, o)[0]
def u16be(b, o): return struct.unpack_from(">H", b, o)[0]
def u64be(b, o): return struct.unpack_from(">Q", b, o)[0]
def u32(b, o, be): return struct.unpack_from(">I" if be else "<I", b, o)[0]
def i32(b, o, be): return struct.unpack_from(">i" if be else "<i", b, o)[0]
def u16(b, o, be): return struct.unpack_from(">H" if be else "<H", b, o)[0]
def u64(b, o, be): return struct.unpack_from(">Q" if be else "<Q", b, o)[0]

def cstr(b, off, maxlen=256):
    end = min(off+maxlen, len(b))
    i = off
    while i < end and b[i] != 0: i += 1
    try: return b[off:i].decode("utf-8", "replace"), i+1
    except: return "".join(chr(x) for x in b[off:i]), i+1

def read_aligned_string(b, off, be):
    if off+4 > len(b): return None
    ln = struct.unpack_from(">i" if be else "<i", b, off)[0]
    if ln < 0 or ln > 4*1024*1024: return None
    if off+4+ln > len(b): return None
    s = b[off+4:off+4+ln]
    try: s = s.decode("utf-8", "replace")
    except: s = "".join(chr(x) for x in s)
    nxt = off+4+ln
    nxt = (nxt+3) & ~3
    return {"str": s, "next": nxt, "len": ln}

CLASS_NAMES = {1:"GameObject",4:"Transform",21:"Material",28:"Texture2D",43:"Mesh",48:"Shader",
    49:"TextAsset",74:"AnimationClip",83:"AudioClip",114:"MonoBehaviour",115:"MonoScript",
    213:"Sprite",106:"Camera",67:"Light",128:"Rigidbody",156:"TerrainData"}
def class_name(cid):
    if cid < 0: return "MonoBehaviour(script %d)" % cid
    return CLASS_NAMES.get(cid, "Class_%d" % cid)

TEX_NAMES = {1:"Alpha8",2:"ARGB4444",3:"RGB24",4:"RGBA32",5:"ARGB32",7:"RGB565",10:"DXT1",12:"DXT5",
    13:"RGBA4444",14:"BGRA32",32:"PVRTC_RGB4",33:"PVRTC_RGBA4",34:"ETC_RGB4",45:"ETC2_RGB4",
    47:"ETC2_RGBA8",48:"ASTC_4x4",49:"ASTC_5x5",50:"ASTC_6x6",51:"ASTC_8x8"}

# ---------- LZ4 (pure Python) ----------
def lz4_decompress(src, dst_size):
    dst = bytearray(dst_size)
    s = d = 0
    while s < len(src):
        tok = src[s]; s += 1
        lit = tok >> 4
        while lit == 15:
            bb = src[s]; s += 1; lit += bb
            if bb != 255: break
        dst[d:d+lit] = src[s:s+lit]; s += lit; d += lit
        if s >= len(src): break
        off = src[s] | (src[s+1] << 8); s += 2
        mlen = tok & 0x0F
        while mlen == 15:
            bb = src[s]; s += 1; mlen += bb
            if bb != 255: break
        mlen += 4
        start = d - off
        for i in range(mlen):
            dst[d+i] = dst[start+i]
        d += mlen
    return bytes(dst[:d])

def decompress_block(ctype, data, out_size):
    if ctype == 0: return bytes(data)
    if ctype in (2,3): return lz4_decompress(data, out_size)
    if ctype == 1:  # LZMA: UnityFS uses raw LZMA stream with 5-byte properties header
        if not _HAS_LZMA:
            raise ValueError("LZMA não disponível neste ambiente Python.")
        try:
            props = data[:5]
            filt = [{"id": _lzma.FILTER_LZMA1, "dict_size": struct.unpack_from("<I", props, 1)[0],
                     "lc": props[0] % 9, "lp": (props[0] // 9) % 5, "pb": props[0] // 45}]
            dec2 = _lzma.LZMADecompressor(format=_lzma.FORMAT_RAW, filters=filt)
            out = dec2.decompress(data[5:], max_length=out_size)
            return out
        except Exception as e:
            raise ValueError("LZMA: " + str(e))
    raise ValueError("Unknown compression type %d" % ctype)

# ---------- UnityFS bundle ----------
def parse_bundle(buf):
    b = buf
    sig, p = cstr(b, 0, 13)
    if sig not in ("UnityFS","UnityWeb","UnityRaw","UnityArchive"):
        raise ValueError("Not a UnityFS bundle (sig=%r)" % sig[:16])
    if sig == "UnityArchive":
        fver = 6
    else:
        fver = u32be(b, p); p += 4
    if fver not in (6,7):
        raise ValueError("Unsupported bundle version %d" % fver)
    minPlayer, p = cstr(b, p, 24)
    engine, p = cstr(b, p, 64)
    total = u64be(b, p); p += 8
    compInfo = u32be(b, p); p += 4
    decInfo = u32be(b, p); p += 4
    flags = u32be(b, p); p += 4
    infoCtype = flags & 0x3F
    infoAtEnd = bool(flags & 0x80)
    if infoAtEnd:
        infoOff = total - compInfo
    else:
        ret = len(minPlayer) + len(engine) + 0x1A
        if flags & 0x100: ret += 0x0A
        else: ret += len(sig) + 1
        if fver >= 7: ret = (ret+15) & ~15
        infoOff = ret
    dataOff = 0
    if sig == "UnityArchive":
        dataOff = compInfo
    elif sig in ("UnityFS","UnityWeb"):
        dataOff = len(minPlayer)+len(engine)+0x1A
        if flags & 0x100: dataOff += 0x0A
        else: dataOff += len(sig)+1
        if fver >= 7: dataOff = (dataOff+15) & ~15
    if not infoAtEnd:
        dataOff += compInfo
        if flags & 0x200: dataOff = (dataOff+15) & ~15
    infoRaw = decompress_block(infoCtype, b[infoOff:infoOff+compInfo], decInfo)
    ip = 0
    _ckL = u64be(infoRaw, ip); ip += 8
    _ckH = u64be(infoRaw, ip); ip += 8
    blockCount = u32be(infoRaw, ip); ip += 4
    blocks = []
    for _ in range(blockCount):
        ds = u32be(infoRaw, ip); ip += 4
        cs = u32be(infoRaw, ip); ip += 4
        bf = u16be(infoRaw, ip); ip += 2
        blocks.append({"ds":ds,"cs":cs,"ctype":bf&0x3F})
    dirCount = u32be(infoRaw, ip); ip += 4
    entries = []
    for _ in range(dirCount):
        off = u64be(infoRaw, ip); ip += 8
        ds = u64be(infoRaw, ip); ip += 8
        fl = u32be(infoRaw, ip); ip += 4
        nm, ip = cstr(infoRaw, ip, 4096)
        entries.append({"name":nm,"offset":off,"size":ds,"flags":fl})
    # decompress data blocks
    cur = dataOff
    dec_blocks = []
    for blk in blocks:
        dec_blocks.append(decompress_block(blk["ctype"], b[cur:cur+blk["cs"]], blk["ds"]))
        cur += blk["cs"]
    uncomp = b"".join(dec_blocks)
    for e in entries:
        e["data"] = uncomp[e["offset"]:e["offset"]+e["size"]]
        e["isAssets"] = detect_assets(e["data"])
    return {"signature":sig,"fileVersion":fver,"engine":engine,"minPlayer":minPlayer,
            "totalSize":total,"compression":["None","LZMA","LZ4","LZ4HC"][infoCtype] if infoCtype<4 else "Type%d"%infoCtype,
            "blocks":blocks,"entries":entries}

def detect_assets(data):
    if len(data) < 20: return False
    fmt1 = u32be(data, 8) if len(data) > 12 else 0
    fmt2 = u32be(data, 12) if len(data) > 16 else 0
    return (1 <= fmt1 <= 30) or (1 <= fmt2 <= 30)

# ---------- .assets file ----------
def info_size(ver):
    if ver >= 0x16: return 24
    if ver >= 0x11: return 20
    if ver >= 0x10: return 23
    if ver >= 0x0F: return 25
    if ver == 0x0E: return 24
    return 20

def parse_assets(data):
    b = data
    p = 0
    dw00 = u32be(b, p); p += 4
    dw04 = u32be(b, p); p += 4
    fmt = u32be(b, p); p += 4
    dw0C = u32be(b, p); p += 4
    if not fmt or fmt > 0x40:
        raise ValueError("Invalid .assets format %d" % fmt)
    hdr = {"format": fmt}
    if fmt >= 0x16:
        hdr["metadataSize"] = u64be(b, p); p += 8
        hdr["fileSize"] = u64be(b, p); p += 8
        hdr["dataOffset"] = u64be(b, p); p += 8
        endian = b[p]; p += 1; p += 7
    else:
        hdr["metadataSize"] = dw00
        hdr["fileSize"] = dw04
        hdr["dataOffset"] = dw0C
        if fmt < 9 and hdr["fileSize"] > hdr["metadataSize"]:
            endian = b[hdr["fileSize"] - hdr["metadataSize"]]
        else:
            endian = b[p]; p += 1; p += 3
    hdr["endianness"] = endian
    be = (endian == 1)
    if fmt < 9:
        filePos = hdr["fileSize"] - hdr["metadataSize"] + 1
    else:
        filePos = p
    unityVer = ""; platform = 0
    if fmt > 6:
        unityVer, filePos = cstr(b, filePos, 64)
        platform = u32(b, filePos, be); filePos += 4
    hasTT = True
    if fmt >= 0x0D:
        hasTT = b[filePos] != 0; filePos += 1
    typeCount = u32(b, filePos, be); filePos += 4
    typeClassIds = []
    if fmt >= 0x0D:
        for _ in range(typeCount):
            cid = i32(b, filePos, be); filePos += 4
            typeClassIds.append(cid)
            if fmt >= 0x10: filePos += 1
            scriptIdx = 0xFFFF
            if fmt >= 0x11: scriptIdx = u16(b, filePos, be); filePos += 2
            if cid < 0 or cid == 114 or scriptIdx != 0xFFFF: filePos += 16
            filePos += 16  # typeHash
            if hasTT:
                vc = u32(b, filePos, be); filePos += 4
                sl = u32(b, filePos, be); filePos += 4
                fsz = 32 if fmt >= 0x12 else 24
                filePos += vc * fsz + sl
                if fmt >= 0x15:
                    dl = i32(b, filePos, be); filePos += 4
                    if dl >= 0: filePos += dl * 4
                    for _ in range(3):
                        _s, filePos = cstr(b, filePos, 4096)
    if fmt < 0x0E:
        filePos += 4
    assetCount = u32(b, filePos, be); filePos += 4
    if fmt >= 0x0E and assetCount > 0:
        filePos = (filePos + 3) & ~3
    sz = info_size(fmt)
    assets = []
    for i in range(assetCount):
        ep = filePos + i * sz
        if fmt >= 0x0E: ep = (ep + 3) & ~3
        if fmt >= 0x0E: pid = u64(b, ep, be); ep += 8
        else: pid = u32(b, ep, be); ep += 4
        if fmt >= 0x16: off = u64(b, ep, be); ep += 8
        else: off = u32(b, ep, be); ep += 4
        asz = u32(b, ep, be); ep += 4
        ti = u32(b, ep, be); ep += 4
        cid = typeClassIds[ti] if (fmt >= 0x10 and ti < len(typeClassIds)) else ti
        assets.append({"pathId":pid,"offset":off,"size":asz,"typeIndex":ti,"classId":cid,"typeName":class_name(cid)})
    return {"header":hdr,"unityVersion":unityVer,"platform":platform,"typeCount":typeCount,
            "assetCount":assetCount,"assets":assets,"data":b}

def extract_asset(parsed, ast):
    off = ast["offset"]
    if off < parsed["header"]["dataOffset"]:
        off = parsed["header"]["dataOffset"] + off
    return parsed["data"][off:off+ast["size"]]

def asset_name(parsed, ast):
    try:
        d = extract_asset(parsed, ast)
        r = read_aligned_string(d, 0, parsed["header"]["endianness"]==1)
        if r and 0 < len(r["str"]) < 200:
            if all(ord(c) >= 32 or c in "\t\n" for c in r["str"]):
                return r["str"]
    except: pass
    return ""

# ---------- Texture decode ----------
def _exp5(v): return (v<<3)|(v>>2)
def _exp6(v): return (v<<2)|(v>>4)

def decode_dxt1(data, w, h):
    out = bytearray(w*h*4)
    bw = (w+3)//4; bh = (h+3)//4; p = 0
    for by in range(bh):
        for bx in range(bw):
            c0 = data[p] | (data[p+1]<<8); c1 = data[p+2] | (data[p+3]<<8)
            bits = data[p+4] | (data[p+5]<<8) | (data[p+6]<<16) | (data[p+7]<<24); p += 8
            r0,g0,b0 = _exp5(c0&0x1F), _exp6((c0>>5)&0x3F), _exp5((c0>>11)&0x1F)
            r1,g1,b1 = _exp5(c1&0x1F), _exp6((c1>>5)&0x3F), _exp5((c1>>11)&0x1F)
            cr=[r0,r1,0,0]; cg=[g0,g1,0,0]; cb=[b0,b1,0,0]; ca=[255,255,0,255]
            if c0 > c1:
                cr[2]=(2*r0+r1)//3; cg[2]=(2*g0+g1)//3; cb[2]=(2*b0+b1)//3; ca[2]=255
                cr[3]=(r0+2*r1)//3; cg[3]=(g0+2*g1)//3; cb[3]=(b0+2*b1)//3; ca[3]=255
            else:
                cr[2]=(r0+r1)//2; cg[2]=(g0+g1)//2; cb[2]=(b0+b1)//2; ca[2]=255; ca[3]=0
            for py in range(4):
                for px in range(4):
                    x=bx*4+px; y=by*4+py
                    if x>=w or y>=h: continue
                    idx = (bits >> (2*(py*4+px))) & 3
                    o=(y*w+x)*4
                    out[o]=cr[idx]; out[o+1]=cg[idx]; out[o+2]=cb[idx]; out[o+3]=ca[idx]
    return bytes(out)

def decode_dxt5(data, w, h):
    out = bytearray(w*h*4)
    bw=(w+3)//4; bh=(h+3)//4; p=0
    for by in range(bh):
        for bx in range(bw):
            a0=data[p]; a1=data[p+1]
            alo = data[p+2]|(data[p+3]<<8)|(data[p+4]<<16)|(data[p+5]<<24)
            ahi = data[p+6]|(data[p+7]<<8)
            a64 = (ahi << 32) | alo
            p += 8
            c0 = data[p]|(data[p+1]<<8); c1 = data[p+2]|(data[p+3]<<8)
            bits = data[p+4]|(data[p+5]<<8)|(data[p+6]<<16)|(data[p+7]<<24); p += 8
            aval=[a0,a1,0,0,0,0,0,0]
            if a0 > a1:
                for i in range(2,8): aval[i]=((8-i)*a0+(i-1)*a1)//7
            else:
                for i in range(2,6): aval[i]=((6-i)*a0+(i-1)*a1)//5
                aval[6]=0; aval[7]=255
            r0,g0,b0=_exp5(c0&0x1F),_exp6((c0>>5)&0x3F),_exp5((c0>>11)&0x1F)
            r1,g1,b1=_exp5(c1&0x1F),_exp6((c1>>5)&0x3F),_exp5((c1>>11)&0x1F)
            cr=[r0,r1,(2*r0+r1)//3,(r0+2*r1)//3]
            cg=[g0,g1,(2*g0+g1)//3,(g0+2*g1)//3]
            cb=[b0,b1,(2*b0+b1)//3,(b0+2*b1)//3]
            for py in range(4):
                for px in range(4):
                    x=bx*4+px; y=by*4+py
                    if x>=w or y>=h: continue
                    aidx = (a64 >> (3*(py*4+px))) & 7
                    cidx = (bits >> (2*(py*4+px))) & 3
                    o=(y*w+x)*4
                    out[o]=cr[cidx]; out[o+1]=cg[cidx]; out[o+2]=cb[cidx]; out[o+3]=aval[aidx]
    return bytes(out)

def decode_raw(data, w, h, fmt):
    out = bytearray(w*h*4); p = 0
    for i in range(w*h):
        o = i*4
        if fmt == 4:
            out[o]=data[p]; out[o+1]=data[p+1]; out[o+2]=data[p+2]; out[o+3]=data[p+3]; p+=4
        elif fmt in (5,14):
            a,r,g,bb = data[p],data[p+1],data[p+2],data[p+3]; p+=4
            out[o]=r; out[o+1]=g; out[o+2]=bb; out[o+3]=a
        elif fmt == 3:
            out[o]=data[p]; out[o+1]=data[p+1]; out[o+2]=data[p+2]; out[o+3]=255; p+=3
        elif fmt == 1:
            out[o]=data[p]; out[o+1]=data[p]; out[o+2]=data[p]; out[o+3]=data[p]; p+=1
        elif fmt == 7:
            v = data[p]|(data[p+1]<<8); p+=2
            out[o]=_exp5((v>>11)&0x1F); out[o+1]=_exp6((v>>5)&0x3F); out[o+2]=_exp5(v&0x1F); out[o+3]=255
        elif fmt in (2,13):
            v = data[p]|(data[p+1]<<8); p+=2
            out[o]=((v>>8)&0xF)*17; out[o+1]=((v>>4)&0xF)*17; out[o+2]=(v&0xF)*17; out[o+3]=((v>>12)&0xF)*17
    return bytes(out)

def parse_texture(asset_bytes, be):
    r = read_aligned_string(asset_bytes, 0, be)
    name = r["str"] if r else ""
    start = r["next"] if r else 4
    found = None
    for off in range(start, min(start+96, len(asset_bytes)-16), 4):
        w = u32(asset_bytes, off, be)
        h = u32(asset_bytes, off+4, be)
        cs = u32(asset_bytes, off+8, be)
        fmt = i32(asset_bytes, off+12, be)
        if 1<=w<=16384 and 1<=h<=16384 and 1<=cs<=len(asset_bytes) and 0<=fmt<=200:
            found = (w,h,cs,fmt); break
    if not found:
        return {"error":"Não foi possível identificar o cabeçalho da textura.","name":name}
    w,h,cs,fmt = found
    fmtName = TEX_NAMES.get(fmt, "Format_%d"%fmt)
    img = asset_bytes[len(asset_bytes)-cs:]
    rgba = None; png = None
    if fmt == 10: rgba = decode_dxt1(img, w, h)
    elif fmt == 12: rgba = decode_dxt5(img, w, h)
    elif fmt in (1,2,3,4,5,7,13,14): rgba = decode_raw(img, w, h, fmt)
    if rgba:
        try:
            from PIL import Image
            im = Image.frombytes("RGBA", (w,h), rgba)
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            png = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception as e:
            png = None
    return {"name":name,"width":w,"height":h,"format":fmtName,"fmt":fmt,
            "png":png,"unsupported": rgba is None, "imgLen": cs}

# ---------- top-level API (called from JS) ----------
def handle_file(buf):
    """buf: bytes. Returns JSON string with full structure."""
    buf = bytes(buf)
    result = {"kind": None, "error": None}
    try:
        b = parse_bundle(buf)
        result["kind"] = "bundle"
        result["info"] = {"signature":b["signature"],"fileVersion":b["fileVersion"],
            "engine":b["engine"],"minPlayer":b["minPlayer"],"totalSize":b["totalSize"],
            "compression":b["compression"],"blockCount":len(b["blocks"]),"entryCount":len(b["entries"])}
        ents = []
        for e in b["entries"]:
            ent = {"name":e["name"],"size":e["size"],"isAssets":e["isAssets"]}
            if e["isAssets"]:
                try:
                    pa = parse_assets(e["data"])
                    ent["assets"] = [{"pathId":a["pathId"],"offset":a["offset"],"size":a["size"],
                        "classId":a["classId"],"typeName":a["typeName"],"name":asset_name(pa,a)} for a in pa["assets"]]
                    ent["unityVersion"] = pa["unityVersion"]
                    ent["assetCount"] = pa["assetCount"]
                except Exception as ex:
                    ent["assetsError"] = str(ex)
            ents.append(ent)
        result["entries"] = ents
        # cache raw bytes for later export (not in JSON)
        _CACHE["bundle"] = b
        return json.dumps(result)
    except Exception as ex:
        try:
            pa = parse_assets(buf)
            result["kind"] = "assets"
            result["info"] = {"format":pa["header"]["format"],"unityVersion":pa["unityVersion"],
                "platform":pa["platform"],"assetCount":pa["assetCount"]}
            result["assets"] = [{"pathId":a["pathId"],"offset":a["offset"],"size":a["size"],
                "classId":a["classId"],"typeName":a["typeName"],"name":asset_name(pa,a)} for a in pa["assets"]]
            _CACHE["assets"] = pa
            return json.dumps(result)
        except Exception as ex2:
            result["error"] = "Bundle: %s | Assets: %s" % (ex, ex2)
            return json.dumps(result)

_CACHE = {}

def get_texture_preview(entry_idx, asset_idx):
    """Returns JSON string with texture info + PNG data URL."""
    try:
        if _CACHE.get("bundle"):
            entry = _CACHE["bundle"]["entries"][entry_idx]
            pa = parse_assets(entry["data"])
            ast = pa["assets"][asset_idx]
            ab = extract_asset(pa, ast)
        elif _CACHE.get("assets"):
            pa = _CACHE["assets"]
            ast = pa["assets"][asset_idx]
            ab = extract_asset(pa, ast)
        else:
            return json.dumps({"error":"no file loaded"})
        tex = parse_texture(ab, pa["header"]["endianness"]==1)
        return json.dumps(tex)
    except Exception as e:
        return json.dumps({"error": str(e)})

def get_asset_bytes(entry_idx, asset_idx):
    """Returns base64 of raw asset bytes for download."""
    try:
        if _CACHE.get("bundle"):
            entry = _CACHE["bundle"]["entries"][entry_idx]
            pa = parse_assets(entry["data"])
            ast = pa["assets"][asset_idx]
            ab = extract_asset(pa, ast)
        elif _CACHE.get("assets"):
            pa = _CACHE["assets"]
            ast = pa["assets"][asset_idx]
            ab = extract_asset(pa, ast)
        else:
            return ""
        return base64.b64encode(bytes(ab)).decode()
    except:
        return ""

def get_entry_bytes(entry_idx):
    if _CACHE.get("bundle"):
        return base64.b64encode(bytes(_CACHE["bundle"]["entries"][entry_idx]["data"])).decode()
    return ""

# ---------- Smart texture export (PNG when decodable, else KTX container) ----------
_KTX_GL = {
    32: (0x8C00, 0x1907),   # PVRTC_RGB4  -> GL_COMPRESSED_RGB_PVRTC_4BPPV1_IMG, GL_RGB
    33: (0x8C02, 0x1908),   # PVRTC_RGBA4 -> GL_COMPRESSED_RGBA_PVRTC_4BPPV1_IMG, GL_RGBA
    34: (0x8D64, 0x1907),   # ETC1_RGB4   -> GL_ETC1_RGB8_OES, GL_RGB
    45: (0x9274, 0x1907),   # ETC2_RGB8
    46: (0x9276, 0x1908),   # ETC2_RGBA8 (RGB4+A1)
    47: (0x9278, 0x1908),   # ETC2_RGBA8
    48: (0x93B0, 0x1908),   # ASTC 4x4 RGBA
    49: (0x93B1, 0x1908), 50: (0x93B2, 0x1908), 51: (0x93B3, 0x1908), 52: (0x93B4, 0x1908), 53: (0x93B5, 0x1908),
}

def _ktx_wrap(img_data, w, h, fmt):
    glif, base = _KTX_GL.get(fmt, (0, 0x1907))
    if glif == 0:
        return None  # unknown format -> caller falls back to bin
    ident = bytes([0xAB, 0x4B, 0x54, 0x58, 0x20, 0x31, 0x31, 0xBB, 0x0D, 0x0A, 0x1A, 0x0A])
    hdr = struct.pack("<12sIIIIIIIIIIIII", ident, 0x04030201, 0, 1, 0, glif, base, w, h, 0, 0, 1, 1, 0)
    size = len(img_data)
    pad = (4 - (size % 4)) % 4
    return hdr + struct.pack("<I", size) + bytes(img_data) + bytes(pad)

def export_texture(entry_idx, asset_idx):
    """Returns JSON: {filename, base64, kind}. PNG if decodable, else KTX container."""
    try:
        if _CACHE.get("bundle"):
            entry = _CACHE["bundle"]["entries"][entry_idx]
            pa = parse_assets(entry["data"])
        elif _CACHE.get("assets"):
            pa = _CACHE["assets"]
        else:
            return json.dumps({"error": "no file"})
        ast = pa["assets"][asset_idx]
        ab = extract_asset(pa, ast)
        tex = parse_texture(ab, pa["header"]["endianness"] == 1)
        name = (tex.get("name") or ast["typeName"]).replace("/", "_")
        if tex.get("png"):
            b64 = tex["png"].split(",", 1)[1]
            return json.dumps({"filename": name + ".png", "base64": b64, "kind": "PNG"})
        ktx = _ktx_wrap(tex.get("imgLen") and ab[-tex["imgLen"]:], tex["width"], tex["height"], tex.get("fmt", 0))
        if ktx:
            return json.dumps({"filename": name + ".ktx", "base64": base64.b64encode(ktx).decode(), "kind": "KTX (" + tex["format"] + ")"})
        # fallback: raw bin
        return json.dumps({"filename": name + ".bin", "base64": base64.b64encode(bytes(ab)).decode(), "kind": "raw"})
    except Exception as e:
        return json.dumps({"error": str(e)})
