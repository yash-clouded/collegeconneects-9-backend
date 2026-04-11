from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class StudentCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1)
    email: EmailStr
    phone: Optional[str] = Field(default=None, min_length=1)
    gender: Optional[str] = ""
    state: Optional[str] = ""
    academic_status: Optional[str] = Field(default="", alias="academicStatus")
    jee_mains_percentile: Optional[str] = Field(default="", alias="jeeMainsPercentile")
    jee_mains_rank: Optional[str] = Field(default="", alias="jeeMainsRank")
    jee_advanced_rank: Optional[str] = Field(default=None, alias="jeeAdvancedRank")
    languages: list[str] = Field(default_factory=list)
    language_other: Optional[str] = Field(default=None, alias="languageOther")
    # Optional avatar: S3 object key from presigned upload (not a data URL when S3 is configured).
    profile_picture: Optional[str] = Field(default=None, alias="profilePicture")







    referral_code: Optional[str] = Field(default=None, alias="referralCode")

    @field_validator("referral_code", mode="before")
    @classmethod
    def strip_referral_code(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("jee_mains_percentile", "jee_mains_rank", mode="before")
    @classmethod
    def jee_mains_as_str(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v)

    @field_validator(
        "jee_advanced_rank",
        "language_other",
        "profile_picture",
        mode="before",
    )
    @classmethod
    def optional_str(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v)


class StudentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    email: EmailStr
    name: str
    created_at: datetime
    total_spent: float = 0.0
    total_sessions: int = 0
