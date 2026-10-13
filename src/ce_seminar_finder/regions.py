"""Explicit rollout boundaries; no geography inferred from event venue."""
REGIONS = {
    "kyushu": ("fukuoka", "saga", "nagasaki", "kumamoto", "oita", "miyazaki", "kagoshima", "okinawa"),
    "chugoku-shikoku": ("tottori", "shimane", "okayama", "hiroshima", "yamaguchi", "tokushima", "kagawa", "ehime", "kochi"),
    "kansai": ("shiga", "kyoto", "osaka", "hyogo", "nara", "wakayama"),
    "tokai-hokuriku": ("gifu", "shizuoka", "aichi", "mie", "toyama", "ishikawa", "fukui"),
    "national": ("jace",),
}


def region_source_ids(region: str) -> set[str]:
    if region == "west":
        return {"src_" + name for names in REGIONS.values() for name in names}
    return {"src_" + name for name in REGIONS[region]}
