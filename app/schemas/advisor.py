from datetime import datetime

from typing import Optional



from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator





class AdvisorCreate(BaseModel):

    model_config = ConfigDict(populate_by_name=True)



    name: str = Field(min_length=1)

    gender: str

    college_email: EmailStr = Field(alias="collegeEmail")

    detected_college: str = Field(alias="detectedCollege")

    branch: str

    phone: Optional[str] = Field(default=None, min_length=1)



    personal_email: Optional[EmailStr] = Field(default=None, alias="personalEmail")

    state: str

    jee_mains_percentile: str = Field(alias="jeeMainsPercentile")

    jee_mains_rank: str = Field(alias="jeeMainsRank")

    jee_advanced_rank: Optional[str] = Field(default=None, alias="jeeAdvancedRank")

    bio: Optional[str] = None





    languages: list[str] = Field(default_factory=list)

    language_other: Optional[str] = Field(default=None, alias="languageOther")

    profile_picture: Optional[str] = Field(default=None, alias="profilePicture")

    preferred_timezones: list[str] = Field(default_factory=list, alias="preferredTimezones")

    session_price: str = Field(alias="sessionPrice")

    # Acknowledgment checkbox; college ID + optional profile photo live in S3 — we store object keys only.

    college_id_acknowledged: bool = Field(default=False, alias="collegeIdAcknowledged")

    college_id_front_key: Optional[str] = Field(default=None, alias="collegeIdFrontKey")

    college_id_back_key: Optional[str] = Field(default=None, alias="collegeIdBackKey")

    id_upload_token: Optional[str] = Field(default=None, alias="idUploadToken")

    referral_code: Optional[str] = Field(default=None, alias="referralCode")



    @field_validator("referral_code", mode="before")

    @classmethod

    def strip_referral_code(cls, v: object) -> str | None:

        if v is None or v == "":

            return None

        s = str(v).strip()

        return s if s else None



    @field_validator("personal_email", mode="before")

    @classmethod

    def empty_personal_email(cls, v: object) -> object:

        if v is None or v == "":

            return None

        return v



    @field_validator("jee_mains_percentile", "jee_mains_rank", "session_price", mode="before")

    @classmethod

    def numeric_fields_as_str(cls, v: object) -> str:

        if v is None:

            return ""

        return str(v)



    @field_validator(
        "jee_advanced_rank",
        "language_other",
        "profile_picture",
        "college_id_front_key",
        "college_id_back_key",
        "id_upload_token",
        mode="before",
    )

    @classmethod

    def optional_str(cls, v: object) -> str | None:

        if v is None or v == "":

            return None

        return str(v)


    @field_validator("preferred_timezones", mode="before")

    @classmethod

    def validate_preferred_timezones(cls, v: object) -> list[str]:

        if v is None:

            return []

        if not isinstance(v, list):

            raise ValueError("preferredTimezones must be a list of time ranges")

        cleaned = [str(item).strip() for item in v if str(item).strip()]

        if len(cleaned) < 4:

            raise ValueError("Add at least 4 preferred time slots")

        return cleaned





class AdvisorResponse(BaseModel):

    model_config = ConfigDict(populate_by_name=True)



    id: str

    college_email: EmailStr

    name: str

    created_at: datetime

