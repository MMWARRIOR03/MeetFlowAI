"""
SQLAlchemy database models for MeetFlow AI system.
Uses SQLAlchemy 2.0 mapped_column syntax with async support.
"""
from datetime import datetime, date
from typing import List, Optional
from sqlalchemy import String, Text, Date, DateTime, Float, Boolean, Integer, JSON, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class Meeting(Base):
    """Meeting record with transcript and metadata."""
    __tablename__ = "meetings"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    participants: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    transcript: Mapped[List[dict]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, default="processing")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    decisions: Mapped[List["Decision"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    audit_entries: Mapped[List["AuditEntry"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")


class Decision(Base):
    """Extracted decision with workflow routing."""
    __tablename__ = "decisions"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    deadline: Mapped[date] = mapped_column(Date, nullable=False)
    workflow_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    approval_status: Mapped[str] = mapped_column(String, default="pending")
    auto_trigger: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    raw_quote: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    meeting: Mapped["Meeting"] = relationship(back_populates="decisions")
    workflow_results: Mapped[List["WorkflowResult"]] = relationship(back_populates="decision", cascade="all, delete-orphan")
    audit_entries: Mapped[List["AuditEntry"]] = relationship(back_populates="decision", cascade="all, delete-orphan")


class AuditEntry(Base):
    """Append-only audit trail for all agent actions."""
    __tablename__ = "audit_entries"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[Optional[str]] = mapped_column(ForeignKey("meetings.id"), nullable=True)
    decision_id: Mapped[Optional[str]] = mapped_column(ForeignKey("decisions.id"), nullable=True)
    agent: Mapped[str] = mapped_column(String, nullable=False)
    step: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)  # success, failure, pending
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_call: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    meeting: Mapped[Optional["Meeting"]] = relationship(back_populates="audit_entries")
    decision: Mapped[Optional["Decision"]] = relationship(back_populates="audit_entries")


class WorkflowResult(Base):
    """Result of workflow execution."""
    __tablename__ = "workflow_results"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"))
    workflow_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # success, failed, pending_retry
    artifact_links: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    decision: Mapped["Decision"] = relationship(back_populates="workflow_results")
