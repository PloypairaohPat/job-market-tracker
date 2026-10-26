"""SQLAlchemy models. Importing this package registers all tables on Base.metadata."""

from src.models.base import Base
from src.models.company import Company
from src.models.ingestion_run import IngestionRun
from src.models.job import Job
from src.models.job_snapshot import JobSnapshot
from src.models.job_visa_signal import JobVisaSignal
from src.models.lca_case import LcaCase
from src.models.location import Location
from src.models.raw_response import RawResponse
from src.models.skill import JobSkill, Skill

__all__ = [
    "Base",
    "Company",
    "IngestionRun",
    "Job",
    "JobSkill",
    "JobSnapshot",
    "JobVisaSignal",
    "LcaCase",
    "Location",
    "RawResponse",
    "Skill",
]
