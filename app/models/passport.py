from pydantic import BaseModel, ConfigDict


class PassportMrzData(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_code": "P",
                "issuing_country": "ESP",
                "nationality": "ESP",
                "passport_number": "XDF235217",
                "surname": "VINIEGRA PEREZ OLAGARAY",
                "given_names": "ESTEBAN",
                "sex": "M",
                "date_of_birth": "2001-09-01",
                "date_of_expiry": "2029-11-12",
                "personal_number": "RE202407041324",
                "checksum_valid": True,
                "raw_line1": "P<ESPVINIEGRA<PEREZ<OLAGARAY<<ESTEBAN<<<<<<<",
                "raw_line2": "XDF2352177ESP0109017M2911124RE20240704132446",
            }
        }
    )

    document_code: str
    issuing_country: str
    nationality: str
    passport_number: str
    surname: str
    given_names: str
    sex: str
    date_of_birth: str | None
    date_of_expiry: str | None
    personal_number: str | None
    checksum_valid: bool
    raw_line1: str
    raw_line2: str


class PassportData(BaseModel):
    mrz: PassportMrzData
    matches_visible_text: bool
    validation_error: str | None = None
