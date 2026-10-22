"""影像品質檢查：解析度、光線不足、模糊、反光。不呼叫任何付費 API，只用 OpenCV 與 Pillow。

依 EXIF 方向轉正後才量測（手機直拍的照片像素是橫的，轉正後寬高才對）。
判定順序：讀不出圖 → 解析度太低 → 整片過白（反光）→ 太暗 → 沒有清楚邊緣（模糊；連字都變淡則算反光）
→ 照片中間一塊白斑（反光）。太暗排在模糊之前：暗的照片邊緣也弱，會被誤判成模糊。

校準用的照片（只在本機，不進 repo）：營養標示 30 張（手機自拍與網路商品圖）、醫院公開的範例藥袋與處方箋 26 張、
手機實拍 6 張（2 張嚴重模糊、1 張稍糊但讀得出字、3 張清楚，其中 1 張有一點反光），另外即時產生模糊、縮小、
過曝、白斑、變暗的版本。結果：清楚與稍糊的照片全部通過，2 張嚴重模糊與產生的壞照片都被拒。
門檻旁邊寫了各自的量測依據。

不判斷：歪斜、沒拍完整（spec「影像品質檢查」一節明訂不做）；
「不是台灣中文營養標示」要讀到文字後才知道，不在這裡判斷。
"""

from dataclasses import dataclass
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.schemas.enums import RejectReason

# ── 解析度（轉正後的像素）─────────────────────────────────────
# 處方籤範例最小長邊 538，辨識全對；縮成長邊 480 以下的版本要被拒。
# 短邊只擋極端情況：網路上裁成長條的標示圖（1501×259）字仍清楚，不能拒。
MIN_LONG_EDGE = 500
MIN_SHORT_EDGE = 200

# ── 模糊（灰階 Laplacian 變異數，長邊先縮放到 1024，大小不同的照片才能用同一個門檻）─────
# 手機實拍：清楚的最低 137、稍糊但讀得出字 467；嚴重模糊 46、47。門檻 100，
# 寧可放過輕微模糊（字仍讀得出來），也不要叫使用者重拍清楚的照片。
BLUR_LONG_EDGE = 1024
MIN_LAPLACIAN_VAR = 100.0

# ── 太暗（第 90 百分位的灰階）─────────────────────────────────
# 用第 90 百分位而不是最亮的像素：暗照片角落有一盞燈（約 1%）也不會被當成夠亮、接著誤判成模糊。
# 所有原圖最低 196；整張亮度乘 0.35 再加一塊 1% 的燈光，最高 89。門檻 120。
# 不用中位數：紅底的網路商品圖中位數只有 74。
MIN_BRIGHTNESS = 120.0

# ── 反光（接近全白像素比例；接近全白＝灰階 ≥ 250）────────────────
# 1. 整張接近全白比例：網路圖本來就是白底（最高約 0.87），門檻 0.94 只抓幾乎全白的過曝照片
# 2. 沒有清楚邊緣時分辨模糊與過曝：過曝連最暗的字都變淡（最暗 1% 像素 ≥ 180）；清楚照片最高約 130
# 3. 照片中間一塊沒有字的白斑：不碰圖邊、內部沒有字的接近全白區塊，最大一塊占整張 ≥ 0.08。
#    原圖最高約 0.05；加 12% 白斑的版本最低約 0.09。白底網路圖的空白連到圖邊，不算。
#    已知限制：白斑碰到圖邊或和白底連在一起就量不到；表格裡占整張 8% 以上的大空白格會被誤判成反光
#    （校準的 56 張真實照片沒有發生）
GLARE_LEVEL = 250
MAX_WHITE_RATIO = 0.94
WASHED_OUT_INK_LEVEL = 180.0
MAX_GLARE_BLOB_RATIO = 0.08
_BLOB_MIN_SOLIDITY = 0.99
_BLOB_MIN_AREA = 0.005  # 小於整張 0.5% 的白點不必算


@dataclass(frozen=True)
class QualityMeasure:
    width: int  # 轉正後
    height: int
    laplacian_var: float  # 長邊縮放到 BLUR_LONG_EDGE 後
    white_ratio: float
    glare_blob_ratio: float
    ink_level: float  # 最暗 1% 像素的灰階（字的顏色）
    brightness_p90: float  # 第 90 百分位的灰階


def load_upright_gray(content: bytes) -> np.ndarray | None:
    """依 EXIF 轉正後的灰階圖；讀不出來時回傳 None。"""
    try:
        img = Image.open(BytesIO(content))
        img.load()
        return np.asarray(ImageOps.exif_transpose(img).convert("L"))
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        # 壞檔、格式不支援、EXIF 損壞（Pillow 有時拋 SyntaxError）、像素多到像壓縮炸彈，都當作讀不出來
        return None


def measure_gray(gray: np.ndarray) -> QualityMeasure:
    h, w = gray.shape
    scale = BLUR_LONG_EDGE / max(w, h)
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    norm = cv2.resize(gray, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=interp)
    return QualityMeasure(
        width=w,
        height=h,
        laplacian_var=float(cv2.Laplacian(norm, cv2.CV_64F).var()),
        white_ratio=float((gray >= GLARE_LEVEL).mean()),
        glare_blob_ratio=_largest_interior_blob(norm),
        ink_level=float(np.percentile(gray, 1)),
        brightness_p90=float(np.percentile(gray, 90)),
    )


def judge(m: QualityMeasure) -> RejectReason | None:
    if max(m.width, m.height) < MIN_LONG_EDGE or min(m.width, m.height) < MIN_SHORT_EDGE:
        return RejectReason.LOW_RESOLUTION
    if m.white_ratio >= MAX_WHITE_RATIO:
        return RejectReason.GLARE
    if m.brightness_p90 < MIN_BRIGHTNESS:
        return RejectReason.LOW_LIGHT
    if m.laplacian_var < MIN_LAPLACIAN_VAR:
        return RejectReason.GLARE if m.ink_level >= WASHED_OUT_INK_LEVEL else RejectReason.BLUR
    if m.glare_blob_ratio >= MAX_GLARE_BLOB_RATIO:
        return RejectReason.GLARE
    return None


def assess(content: bytes) -> RejectReason | None:
    """一張照片的判定；None ＝ 通過。讀不出圖的檔案算「不支援」，請使用者改拍標示照片。"""
    gray = load_upright_gray(content)
    if gray is None:
        return RejectReason.UNSUPPORTED_LABEL
    return judge(measure_gray(gray))


def _largest_interior_blob(gray: np.ndarray) -> float:
    """不碰圖邊、內部沒有字的接近全白區塊，最大一塊占整張的比例。"""
    mask = (gray >= GLARE_LEVEL).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    h, w = gray.shape
    total = h * w
    best = 0.0
    for i in range(1, count):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        if area < _BLOB_MIN_AREA * total or x == 0 or y == 0 or x + bw == w or y + bh == h:
            continue
        comp = (labels[y : y + bh, x : x + bw] == i).astype(np.uint8)
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(comp)
        cv2.drawContours(filled, contours, -1, 1, thickness=-1)
        if area / max(1, int(filled.sum())) >= _BLOB_MIN_SOLIDITY:
            best = max(best, area / total)
    return best
