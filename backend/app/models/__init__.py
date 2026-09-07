"""Database models. Import from here, not from the module directly."""

from app.models.entities import (
    Asset,
    Category,
    Client,
    DataRecord,
    DataSource,
    DataSourceKind,
    FieldMapping,
    GenerationJob,
    JobStatus,
    Project,
    ProjectStatus,
    RecordResult,
    RecordStatus,
    Role,
    ShortLink,
    Template,
    TemplateField,
    TemplatePage,
    TemplateSection,
    TemplateStatus,
    User,
)

__all__ = [
    "Asset", "Category", "Client", "DataRecord", "DataSource", "DataSourceKind",
    "FieldMapping", "GenerationJob", "JobStatus", "Project", "ProjectStatus",
    "RecordResult", "RecordStatus", "Role", "ShortLink", "Template",
    "TemplateField",
    "TemplatePage", "TemplateSection", "TemplateStatus", "User",
]
