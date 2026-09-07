from typing import Annotated, Literal

from fastapi import Form
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError


class OcrRequestParams(BaseModel):
    """Parametros aceptados por POST /api/v1/ocr.

    Los defaults de cada campo son los "defaults obligatorios" del servicio (no los de
    OCR.space): si el cliente no manda el campo, se usa este valor. El cliente puede
    sobreescribir cualquiera de ellos vía form-data.
    """

    language: str = Field(default="spa", min_length=2, max_length=10)
    ocr_engine: Literal[1, 2, 3] = 2
    detect_orientation: bool = True
    is_create_searchable_pdf: bool = False
    is_overlay_required: bool = False
    is_table: bool = False
    scale: bool = False
    include_raw: bool = False

    @classmethod
    def as_form(
        cls,
        language: Annotated[str, Form()] = "spa",
        # int (not Literal) here: Starlette form values arrive as strings, and pydantic's
        # Literal validator requires an exact type+value match with no str->int coercion,
        # unlike a plain int field. OcrRequestParams.ocr_engine below still enforces {1,2,3}
        # once FastAPI has coerced the form string into a real int.
        ocr_engine: Annotated[int, Form()] = 2,
        detect_orientation: Annotated[bool, Form()] = True,
        is_create_searchable_pdf: Annotated[bool, Form()] = False,
        is_overlay_required: Annotated[bool, Form()] = False,
        is_table: Annotated[bool, Form()] = False,
        scale: Annotated[bool, Form()] = False,
        include_raw: Annotated[bool, Form()] = False,
    ) -> "OcrRequestParams":
        try:
            return cls(
                language=language,
                ocr_engine=ocr_engine,
                detect_orientation=detect_orientation,
                is_create_searchable_pdf=is_create_searchable_pdf,
                is_overlay_required=is_overlay_required,
                is_table=is_table,
                scale=scale,
                include_raw=include_raw,
            )
        except ValidationError as exc:
            # Re-raised as FastAPI's own validation error so it goes through the same
            # 422 envelope as any other request-validation failure, instead of falling
            # through to the generic 500 handler (Depends() callables aren't covered by
            # FastAPI's automatic pydantic-error-to-422 conversion).
            raise RequestValidationError(exc.errors()) from exc
