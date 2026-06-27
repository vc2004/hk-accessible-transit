"""
Multi-language support — Traditional Chinese (zh-HK), Simplified Chinese (zh-CN), English (en).

Auto-detects user language from query and generates context-aware prompts
for the LLM to respond in the same language.
"""

LANG_DETECT = {
    # Traditional Chinese markers (Hong Kong, Taiwan)
    "zh-HK": [
        "嘅", "咗", "喺", "嚟", "哋", "冇", "啲", "嘅", "吓",
        "輪椅", "長者", "無障礙", "港鐵", "巴士", "小巴", "渡輪",
        "請問", "點去", "點樣", "邊度", "呢個", "嗰個",
    ],
    # Simplified Chinese markers (Mainland China)
    "zh-CN": [
        "的", "了", "在", "来", "们", "没", "些",
        "轮椅", "长者", "无障碍", "地铁", "公交",
        "请问", "怎么去", "怎样", "哪里", "这个", "那个",
    ],
}

# System prompt additions for each language
LANG_PROMPTS = {
    "zh-HK": (
        "\n\n請用繁體中文回答。使用香港慣用嘅地名同交通術語"
        "（例如：港鐵、巴士、小巴、渡輪、升降機、無障礙設施）。"
        "車站名用返香港官方嘅英文拼法。"
    ),
    "zh-CN": (
        "\n\n请用简体中文回答。使用中国大陆惯用的地名和交通术语"
        "（例如：地铁、公交车、轮渡、电梯、无障碍设施）。"
        "站名同时提供英文。"
    ),
    "en": "",
}


def detect_language(text: str) -> str:
    """Detect the user's language from their query.

    Returns 'zh-HK' (Traditional), 'zh-CN' (Simplified), or 'en'.
    """
    zh_hk_score = sum(1 for marker in LANG_DETECT["zh-HK"] if marker in text)
    zh_cn_score = sum(1 for marker in LANG_DETECT["zh-CN"] if marker in text)

    if zh_hk_score > zh_cn_score and zh_hk_score > 1:
        return "zh-HK"
    elif zh_cn_score > zh_hk_score and zh_cn_score > 1:
        return "zh-CN"
    elif any('一' <= c <= '鿿' for c in text):
        # Has Chinese characters but can't differentiate → default to HK
        return "zh-HK"
    return "en"


def get_lang_prompt(text: str) -> str:
    """Get the language-specific addition to the system prompt."""
    lang = detect_language(text)
    return LANG_PROMPTS.get(lang, "")
