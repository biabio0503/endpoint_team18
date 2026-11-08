from decimal import Decimal, InvalidOperation
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, ValidationError, field_validator
from api.domain import Problem


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class PlanChanges(StrictModel):
    career_goal: StrictStr | None = None
    target_role: StrictStr | None = None
    university_id: StrictStr | None = None
    department_id: StrictStr | None = None
    catalog_id: StrictStr | None = None
    year_level: StrictInt | None = Field(default=None, ge=1, le=4)
    earned_credits: StrictInt | StrictFloat | None = None
    gpa: StrictInt | StrictFloat | None = None
    gpa_scale: StrictInt | StrictFloat | None = None

    @field_validator('career_goal')
    @classmethod
    def goal_valid(cls, value):
        if value is None or not value.strip() or len(value) > 10000:
            raise ValueError('invalid goal')
        return value

    @field_validator('target_role')
    @classmethod
    def role_valid(cls, value):
        if value is not None and len(value.strip()) > 100:
            raise ValueError('invalid role')
        return value

    @field_validator('university_id', 'department_id', 'catalog_id')
    @classmethod
    def id_valid(cls, value):
        if value is not None and len(value) > 100:
            raise ValueError('invalid identifier')
        return value

    @field_validator('earned_credits', 'gpa', 'gpa_scale')
    @classmethod
    def number_valid(cls, value, info):
        if value is None:
            return value
        maximum, places = (Decimal('9999.9'), 1) if info.field_name == 'earned_credits' else (Decimal('9.99'), 2)
        try:
            number = Decimal(str(value))
            if not number.is_finite() or number < 0 or number > maximum or number != number.quantize(Decimal(1).scaleb(-places)):
                raise ValueError('invalid number')
        except InvalidOperation:
            raise ValueError('invalid number') from None
        return value


class PlanPatch(StrictModel):
    expected_input_revision: StrictInt = Field(ge=0)
    changes: PlanChanges


class CourseChange(StrictModel):
    course_id: StrictStr
    is_completed: StrictBool


class SelectionPatch(StrictModel):
    catalog_id: StrictStr = Field(min_length=1)
    expected_selection_revision: StrictInt = Field(ge=0)
    changes: list[CourseChange] = Field(min_length=1, max_length=100)


class ReviewRequest(StrictModel):
    catalog_id: StrictStr = Field(min_length=1)
    expected_selection_revision: StrictInt = Field(ge=0)
    expected_input_revision: StrictInt = Field(ge=0)
    reported_missing_courses: StrictBool


class RevisionRequest(StrictModel):
    expected_input_revision: StrictInt = Field(ge=0)


class EmptyRequest(StrictModel):
    pass


def validate_body(model, body):
    try:
        return model.model_validate(body)
    except ValidationError:
        raise Problem(422, 'validation_error', '요청 형식을 확인해 주세요.') from None


def openapi_body(model):
    schema = model.model_json_schema()
    definitions = schema.pop('$defs', {})

    def inline(value):
        if isinstance(value, dict):
            if '$ref' in value:
                return inline(definitions[value['$ref'].split('/')[-1]])
            return {key: inline(item) for key, item in value.items()}
        if isinstance(value, list):
            return [inline(item) for item in value]
        return value

    return {'requestBody': {'required': True, 'content': {'application/json': {'schema': inline(schema)}}}}
