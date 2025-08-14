from dataclasses import dataclass
from typing import List, Optional, Tuple
from ..db.company_db import fetch_all, init_db, CompanyRow
from .task_mapping import classify_machine, keywords_for_category
from . import llm


@dataclass
class Match:
    company: CompanyRow
    score: float
    steps: list
    alliance: Optional[List[CompanyRow]] = None  # アライアンス案（任意）


def _split_csv(s: str) -> list:
    return [x.strip() for x in s.split(',') if x.strip()]


def match_companies(process_steps) -> List[Match]:
    # DB初期化（初回のみシード）
    init_db(seed=True)
    companies = fetch_all()
    matches: List[Match] = []
    required_machines = {s.machine for s in process_steps}
    for c in companies:
        c_machines = set(_split_csv(c.machines))
        c_skills = _split_csv(c.skills)
        score = 0.0
        cover = []
        # 機械カバレッジ
        cover_ratio = len(required_machines & c_machines) / max(1, len(required_machines))
        score += 0.6 * cover_ratio
        # 備考/スキルの簡易一致
        text = (" ".join(c_skills) + " " + c.notes).lower()
        for s in process_steps:
            m = s.machine
            if any(k in text for k in ["sus", "ステンレス"]) and ("VMC" in m or "タッピング" in m):
                score += 0.1
            if "タッピング" in m and ("ねじ" in text):
                score += 0.1
        # ステップ割当（対応可能な工程）
        for s in process_steps:
            if s.machine in c_machines:
                cover.append(s.name)
        # カテゴリキーワードによるブースト（設備名の異表記やJP/EN差吸収）
        comp_text = f"{c.machines} {c.skills} {c.notes}".lower()
        for s in process_steps:
            cat = classify_machine(getattr(s, 'machine', ''))
            if not cat:
                continue
            kws = keywords_for_category(cat)
            if not kws:
                continue
            hit = sum(1 for kw in kws if kw and kw in comp_text)
            if hit:
                # 1工程あたり最大+0.15までブースト
                score += min(0.15, 0.02 * hit)
        # LLM補助（説明可能性向上のための微調整、任意）
        if llm.is_configured():
            prompt = f"""
あなたは企業マッチングの評価者です。次の工程要求と企業情報から、適合度boostのみをJSONで出力してください。
スキーマ: {{"boost": "number(0.0-1.0)"}} 以外の出力は禁止。
工程一覧: {', '.join([s.name+'('+s.machine+')' for s in process_steps])}
企業: {c.name}\n機械: {c.machines}\nスキル: {c.skills}\n備考: {c.notes}
            """
            js = llm.chat_json(
                system="企業マッチング評価",
                user=prompt,
                temperature=0.0,
                max_tokens=120,
                timeout=15,
                reasoning_effort="low",
            )
            if isinstance(js, dict):
                try:
                    boost = float(js.get("boost", 0.0))
                    score = min(1.0, max(0.0, score * 0.9 + 0.1 * boost))
                except Exception:
                    pass
        matches.append(Match(c, round(min(score, 1.0), 2), cover))
    matches.sort(key=lambda m: m.score, reverse=True)

    # 単独でカバー不可の場合、簡易アライアンス提案（上位Nから機械カバレッジを貪欲に充足）
    have_full_cover = any(set(m.steps) and len(set(m.steps)) == len(process_steps) for m in matches)
    if not have_full_cover and matches:
        needed = set(s.machine for s in process_steps)
        alliance: List[CompanyRow] = []
        cover_steps: List[str] = []
        for m in matches:
            cm = set(_split_csv(m.company.machines))
            if needed & cm:
                alliance.append(m.company)
                # どの工程が埋まったかを積算
                for s in process_steps:
                    if s.machine in cm:
                        cover_steps.append(s.name)
                needed -= cm
            if not needed:
                break
        # アライアンス提案を先頭マッチに紐付け（UI最小変更のため）
        if alliance:
            matches[0].alliance = alliance
    return matches
