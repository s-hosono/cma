from dataclasses import dataclass
from typing import List, Optional
from . import llm

@dataclass
class ProcessStep:
    name: str
    machine: str
    minutes: int
    tolerance: Optional[str] = None
    precision: Optional[str] = None  # 例: 粗/仕上/検査


def breakdown_process(features) -> List[ProcessStep]:
    steps: List[ProcessStep] = []
    # LLM提案（あれば採用）
    if llm.is_configured():
        prompt = f"""
あなたは工程設計の専門家です。以下の条件で3〜5工程の推奨工程のみをJSON配列で厳密に出力してください。説明文や前置きは禁止。
各要素スキーマ: {"name": "string", "machine": "string", "minutes": "integer", "tolerance": "string(optional)", "precision": "string(optional)"}
前提: 材質={features.material}, 種別={features.part_type}
        """
        js = llm.chat_json(
            system="工程分解",
            user=prompt,
            temperature=0.1,
            max_tokens=500,
            timeout=25,
            reasoning_effort="medium",
        )
        if isinstance(js, list):
            for item in js:
                try:
                    steps.append(
                        ProcessStep(
                            name=str(item.get("name")),
                            machine=str(item.get("machine")),
                            minutes=int(item.get("minutes", 10)),
                            tolerance=item.get("tolerance"),
                            precision=item.get("precision"),
                        )
                    )
                except Exception:
                    pass
    # 極簡易ルール（フォールバック）
    material = (features.material or "").upper()
    if "SUS" in material:
        steps.append(ProcessStep("荒加工", "VMC", 30, precision="粗"))
        steps.append(ProcessStep("穴あけ", "タッピングセンタ", 20, precision="中"))
        steps.append(ProcessStep("仕上げ", "VMC", 25, "±0.05", precision="仕上"))
    else:
        steps.append(ProcessStep("荒加工", "汎用フライス", 20, precision="粗"))
        steps.append(ProcessStep("穴あけ", "ボール盤", 15, precision="中"))
        steps.append(ProcessStep("仕上げ", "フライス盤", 15, "±0.1", precision="仕上"))

    if features.dims_text:
        steps.append(ProcessStep("検査", "三次元測定機", 10, precision="検査"))
    return steps
