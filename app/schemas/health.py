from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "ok", "database": "ok"}]})

    status: str
    database: str
