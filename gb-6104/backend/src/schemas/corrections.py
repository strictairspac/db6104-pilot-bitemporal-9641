from pydantic import BaseModel, Field, field_validator

from src.domain.contract_terms import TOKEN


class CorrectionInput(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    adjustments: dict[str, int]
    note: str = Field(default="", max_length=500)

    @field_validator("code")
    @classmethod
    def check_code(cls, code):
        value = code.strip()
        if not TOKEN.fullmatch(value):
            raise ValueError("更正单号须为 1–30 位大写字母、数字或连字符")
        return value

    @field_validator("adjustments")
    @classmethod
    def check_adjustments(cls, adjustments):
        if not 1 <= len(adjustments) <= 200:
            raise ValueError("更正须有 1–200 条航次吨位")
        for voyage, tons in adjustments.items():
            if not TOKEN.fullmatch(voyage):
                raise ValueError("更正航次须为 1–30 位大写字母、数字或连字符")
            if type(tons) is not int or not 1 <= tons <= 10_000_000:
                raise ValueError("更正吨位须为 1–10000000 的整数")
        return adjustments

    @field_validator("note")
    @classmethod
    def check_note(cls, note):
        return note.strip()


class CorrectionEntry(BaseModel):
    id: int
    code: str
    parent_run_id: int
    run_id: int
    adjustments: dict[str, int]
    note: str
    digest: str
    actor: str
    created_at: int
    replayed: bool = False
