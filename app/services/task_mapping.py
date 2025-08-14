from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Iterable, Optional


@dataclass(frozen=True)
class TaskCategory:
    key: str          # canonical key (lowercase)
    label: str        # display label
    synonyms: Tuple[str, ...]   # words/phrases indicating the task (JP/EN)
    machines: Tuple[str, ...]   # typical equipment names (JP/EN)


# Canonical categories with rich synonyms (JP/EN) and equipment names
_CATS: List[TaskCategory] = [
    TaskCategory(
        key="drilling",
        label="Drilling / 穴あけ",
        synonyms=(
            "drill", "drilling", "穴", "穴あけ", "下穴", "座ぐり", "カウンターボア",
            "ream", "reaming", "リーマ", "boring", "ボーリング",
            "tap", "tapping", "タップ", "タッピング", "ねじ立て",
        ),
        machines=(
            "drill press", "ボール盤", "卓上ボール盤", "tapping center", "タッピングセンタ",
            "リーマ", "ボーリングヘッド",
        ),
    ),
    TaskCategory(
        key="milling",
        label="Milling / フライス",
        synonyms=(
            "mill", "milling", "フライス", "エンドミル", "マシニング", "切削", "端面", "側面",
            "vmc", "hmc", "加工センタ", "マシニングセンタ", "ポケット", "溝削り",
        ),
        machines=(
            "VMC", "立形マシニングセンタ", "HMC", "横形マシニングセンタ", "フライス盤", "汎用フライス",
        ),
    ),
    TaskCategory(
        key="turning",
        label="Turning / 旋削",
        synonyms=(
            "turn", "turning", "lathe", "旋削", "旋盤", "突切り", "外径", "内径",
        ),
        machines=(
            "NC旋盤", "CNC lathe", "旋盤", "複合旋盤",
        ),
    ),
    TaskCategory(
        key="cutting",
        label="Cutting / 切断",
        synonyms=(
            "cut", "cutting", "切断", "レーザ", "レーザー", "plasma", "プラズマ",
            "waterjet", "ウォータージェット", "saw", "ノコ", "バンドソー", "せん断",
        ),
        machines=(
            "レーザー加工機", "ファイバーレーザー", "CO2レーザー", "ウォータージェット", "プラズマ切断機",
            "バンドソー", "丸ノコ", "シャーリング",
        ),
    ),
    TaskCategory(
        key="finishing",
        label="Finishing / 仕上げ",
        synonyms=(
            "finish", "finishing", "研磨", "研削", "polish", "grind", "バフ",
            "deburr", "面取り", "バリ取り", "ラッピング", "ホーニング", "バレル",
        ),
        machines=(
            "研削盤", "平面研削盤", "円筒研削盤", "バレル研磨機", "ブラスト", "ショットブラスト",
        ),
    ),
    TaskCategory(
        key="inspection",
        label="Inspection / 検査",
        synonyms=(
            "inspection", "inspect", "検査", "測定", "計測", "寸法検査", "CMM", "三次元",
        ),
        machines=(
            "三次元測定機", "CMM", "投影機", "マイクロメータ", "ハイトゲージ",
        ),
    ),
]

# Fast lookup maps
TASK_CATEGORIES: Dict[str, TaskCategory] = {c.key: c for c in _CATS}
TASK_CATEGORY_LABELS: Dict[str, str] = {c.key: c.label for c in _CATS}

# Aliases allow old UI names (e.g., Drilling, Milling) to map to keys
ALIASES: Dict[str, str] = {
    "drilling": "drilling", "穴あけ": "drilling", "穴": "drilling", "tap": "drilling", "tapping": "drilling", "タッピング": "drilling",
    "milling": "milling", "フライス": "milling", "マシニング": "milling", "vmc": "milling", "hmc": "milling",
    "cutting": "cutting", "切断": "cutting", "レーザー": "cutting", "waterjet": "cutting", "ウォータージェット": "cutting",
    "finishing": "finishing", "仕上げ": "finishing", "研磨": "finishing", "研削": "finishing",
    "turning": "turning", "旋削": "turning", "旋盤": "turning", "lathe": "turning",
    "inspection": "inspection", "検査": "inspection", "三次元": "inspection", "cmm": "inspection",
}


def _lc_words(xs: Iterable[str]) -> List[str]:
    return sorted({(x or "").strip().lower() for x in xs if (x or "").strip()}, key=lambda s: (len(s), s))


def normalize_category_key(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    k = s.strip().lower()
    return ALIASES.get(k, k if k in TASK_CATEGORIES else None)


def keywords_for_category(key: str) -> List[str]:
    cat = TASK_CATEGORIES.get(key)
    if not cat:
        return []
    return _lc_words(list(cat.synonyms) + list(cat.machines))


def classify_machine(machine: str) -> Optional[str]:
    m = (machine or "").strip().lower()
    if not m:
        return None
    # Check by machines first, then by synonyms
    for cat in _CATS:
        for token in cat.machines:
            if token.lower() in m:
                return cat.key
    for cat in _CATS:
        for token in cat.synonyms:
            if token.lower() in m:
                return cat.key
    return None


def classify_step(step) -> Optional[str]:
    # Try machine, then name
    k = classify_machine(getattr(step, "machine", ""))
    if k:
        return k
    name = (getattr(step, "name", "") or "").lower()
    return normalize_category_key(name)


def categories_for_steps(steps: Iterable) -> List[Tuple[str, str, int]]:
    # Returns list of (key, label, count) for categories present in steps, ordered by a fixed preference
    cnt: Dict[str, int] = {}
    for s in steps or []:
        k = classify_step(s)
        if not k:
            continue
        cnt[k] = cnt.get(k, 0) + 1
    # Order by predefined order in _CATS
    ordered = []
    for cat in _CATS:
        if cnt.get(cat.key):
            ordered.append((cat.key, cat.label, cnt[cat.key]))
    # Fallback: if none detected, suggest common four tabs
    if not ordered:
        for k in ("drilling", "milling", "cutting", "finishing"):
            c = TASK_CATEGORIES[k]
            ordered.append((c.key, c.label, 0))
    return ordered


def steps_by_category(steps: Iterable) -> Dict[str, List[Tuple[int, object]]]:
    res: Dict[str, List[Tuple[int, object]]] = {}
    for idx, s in enumerate(steps or []):
        k = classify_step(s)
        if not k:
            continue
        res.setdefault(k, []).append((idx, s))
    return res
