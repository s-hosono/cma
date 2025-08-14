from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from PIL import Image
import pytesseract
from pdfminer.high_level import extract_text
from . import llm

@dataclass
class Features:
    filename: str
    ext: str
    # メタ
    title: Optional[str] = None
    drawing_no: Optional[str] = None
    # 特徴
    material: Optional[str] = None
    part_type: Optional[str] = None
    surface_finish: Optional[str] = None
    tolerances: Optional[List[str]] = None
    # 推奨加工
    recommended_process: Optional[str] = None
    recommended_machine: Optional[str] = None
    # その他
    notes: Optional[str] = None
    dims_text: Optional[str] = None


def _ocr_image(p: Path) -> str:
    try:
        img = Image.open(p)
        text = pytesseract.image_to_string(img, lang="eng+jpn")
        return text
    except Exception as e:
        return f""


def _extract_text_from_pdf(p: Path) -> str:
    try:
        return extract_text(str(p))
    except Exception:
        return ""


def analyze_file(p: Path) -> Features:
    ext = p.suffix.lower().lstrip('.')
    text = ""
    if ext in {"png", "jpg", "jpeg"}:
        text = _ocr_image(p)
    elif ext == "pdf":
        text = _extract_text_from_pdf(p)
    # DXF/DWGなどは本プロトタイプではOCR対象外

    # LLMが設定されていれば補助推論
    if llm.is_configured():
        prompt = f"""
あなたは製造図面解析の専門家AIです。以下の入力から、次の項目のみを含むJSONを厳密に1つだけ出力してください。説明文やコードブロックは不要です。
スキーマ: {{
    "title": "string(optional)",
    "drawing_no": "string(optional)",
    "part_type": "string",
    "material": "string",
    "surface_finish": "string(optional)",
    "tolerances": "string[] (optional)",
    "recommended_process": "string(optional)",
    "recommended_machine": "string(optional)"
}}
- title: 図面タイトル（分かる場合）
- drawing_no: 図番（分かる場合）
- part_type: 部品種別（例: フランジ/ブラケット/シャフト/プレート など）
- material: 材質（例: SUS304/AL/FC/SS/真鍮 等、推測でよい）
- surface_finish: 表面粗さ（例: Ra1.6 など）
- tolerances: 公差のリスト（例: ["±0.1", "H7", "穴 ±0.02"]）
- recommended_process: 推奨加工種別（例: フライス、旋盤 等）
- recommended_machine: 推奨装置（例: VMC、タッピングセンタ 等）

ファイル名: {p.name}
抽出テキスト（冒頭800文字）: {text[:800]}
        """
        js = llm.chat_json(
            system="製造図面解析",
            user=prompt,
            temperature=0.1,
            max_tokens=300,
            timeout=20,
            reasoning_effort="low",
        ) or {}
        material = js.get("material") if isinstance(js, dict) else None
        part_type = js.get("part_type") if isinstance(js, dict) else None
        title = js.get("title") if isinstance(js, dict) else None
        drawing_no = js.get("drawing_no") if isinstance(js, dict) else None
        surface_finish = js.get("surface_finish") if isinstance(js, dict) else None
        tolerances = js.get("tolerances") if isinstance(js, dict) else None
        recommended_process = js.get("recommended_process") if isinstance(js, dict) else None
        recommended_machine = js.get("recommended_machine") if isinstance(js, dict) else None
    else:
        material = None
        part_type = None
        title = None
        drawing_no = None
        surface_finish = None
        tolerances = None
        recommended_process = None
        recommended_machine = None
    for m in ["SUS", "AL", "FC", "SS", "真鍮", "アルミ", "鋼"]:
        if m in text or m in p.name:
            material = m
            break
    for k in ["ブラケット", "フランジ", "シャフト", "プレート", "ケース", "ハウジング"]:
        if k in text or k in p.name:
            part_type = k
            break

    dims_text = None
    for token in ["φ", "±", "R", "mm", "+0", "-0"]:
        if token in text:
            dims_text = "...寸法表記を検出..."
            break

    # 表面粗さ/公差のヒューリスティック抽出
    if not surface_finish and any(k in text for k in ["Ra", "RA", "ｒａ"]):
        # 簡易抽出（例: Ra1.6 を拾う）
        import re
        m = re.search(r"R[aA]\s*\d+(?:\.\d+)?", text)
        if m:
            surface_finish = m.group(0)
    tol_list: List[str] = []
    for tok in ["±0.01", "±0.02", "±0.05", "±0.1", "±0.20", "H7"]:
        if tok in text:
            tol_list.append(tok)
    if tolerances is None and tol_list:
        tolerances = tol_list

    # 推奨加工/装置の簡易推定
    if not recommended_process:
        if "フランジ" in (part_type or "") or "φ" in (text or ""):
            recommended_process = "旋盤"
        elif "プレート" in (part_type or ""):
            recommended_process = "フライス"
    if not recommended_machine:
        if recommended_process == "旋盤":
            recommended_machine = "NC旋盤"
        elif recommended_process == "フライス":
            recommended_machine = "VMC"

    return Features(
        filename=p.name,
        ext=ext,
        title=title,
        drawing_no=drawing_no,
        material=material,
        part_type=part_type,
        surface_finish=surface_finish,
        tolerances=tolerances,
        recommended_process=recommended_process,
        recommended_machine=recommended_machine,
        notes=(text[:500] if text else None),
        dims_text=dims_text,
    )
