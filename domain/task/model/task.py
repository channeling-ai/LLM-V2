from sqlalchemy import Column
from sqlmodel import SQLModel, Field
from typing import Optional
from enum import Enum
from sqlalchemy import Column, Enum as SAEnum


class Status(str, Enum):
    """작업 상태 Enum"""
    PENDING = "PENDING"  # 대기 중
    COMPLETED = "COMPLETED"  # 완료
    FAILED = "FAILED"  # 실패


class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="report.id", description="리포트 ID")
    overview_status: Status = Field(
        sa_column=Column(
            SAEnum(Status, name="status", native_enum=False),
            nullable=False
        )
    )
    analysis_status: Status = Field(
        sa_column=Column(
            SAEnum(Status, name="status", native_enum=False),
            nullable=False
        )
    )
    idea_status: Status = Field(
        sa_column=Column(
            SAEnum(Status, name="status", native_enum=False),
            nullable=False
        )
    )



