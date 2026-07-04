from __future__ import annotations

from enum import StrEnum


class PublicationStatus(StrEnum):
    PUBLISHED = "公開"
    PRIVATE = "非公開"
    PENDING = "確認待ち"
    ARCHIVED = "アーカイブ"


class ReviewStatus(StrEnum):
    UNREVIEWED = "未確認"
    REVIEWED = "確認済み"
    NEEDS_EDIT = "要修正"


class ReviewLabel(StrEnum):
    YES = "あり"
    NO = "なし"


class DuplicateStatus(StrEnum):
    NONE = "重複なし"
    CANDIDATE = "重複候補"
    MERGED = "統合済み"


class EventType(StrEnum):
    SEMINAR = "セミナー"
    TRAINING = "研修会"
    COURSE = "講習会"
    CONFERENCE = "学会・大会"
    STUDY_GROUP = "研究会"
    ON_DEMAND = "オンデマンド"
    OTHER = "その他"


class EventFormat(StrEnum):
    WEB = "Web"
    ON_DEMAND = "オンデマンド"
    HYBRID = "ハイブリッド"
    ONSITE = "現地開催"
    UNKNOWN = "要確認"


class FeeCategory(StrEnum):
    FREE = "無料"
    PAID = "有料"
    UNKNOWN = "要確認"


class OrganizerType(StrEnum):
    SOCIETY = "技士会主催"
    RELATED = "関連団体主催"
    COMPANY = "企業主催"
    CO_HOSTED = "企業共催"
    UNKNOWN = "要確認"


class Genre(StrEnum):
    BLOOD_PURIFICATION = "血液浄化"
    RESPIRATORY = "呼吸"
    CIRCULATORY = "循環"
    DEVICE_MANAGEMENT = "医療機器管理"
    OPERATING_ROOM = "手術室"
    EDUCATION_RESEARCH = "教育・研究"
    DX_IT = "DX・IT"
    OTHER = "その他"


class ReviewReason(StrEnum):
    DATE_UNKNOWN = "DATE_UNKNOWN"
    DEADLINE_UNKNOWN = "DEADLINE_UNKNOWN"
    FEE_UNKNOWN = "FEE_UNKNOWN"
    CREDITS_UNCERTAIN = "CREDITS_UNCERTAIN"
    PDF_PRIMARY = "PDF_PRIMARY"
    DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE"
    LOW_EVENT_CONFIDENCE = "LOW_EVENT_CONFIDENCE"
    ORGANIZER_UNKNOWN = "ORGANIZER_UNKNOWN"
    FORMAT_UNKNOWN = "FORMAT_UNKNOWN"
    OFFICIAL_URL_UNKNOWN = "OFFICIAL_URL_UNKNOWN"
    SOURCE_UNREACHABLE = "SOURCE_UNREACHABLE"
    TEXT_QUALITY_LOW = "TEXT_QUALITY_LOW"
    HIGH_IMPACT_FIELD_CHANGED = "HIGH_IMPACT_FIELD_CHANGED"
    SOURCE_GAP = "SOURCE_GAP"

