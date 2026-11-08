from enum import Enum

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, MetaData, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

naming_convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}
db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))


class AbcCustomerEntities(Enum):
    AmoCustomer = 'amo_customers'
    AmoLead = 'amo_leads'
    AmoCompany = 'amo_companies'
    AmoContact = 'amo_contacts'
    SendMethods = 'send_methods'


class TimestampMixin:
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class SyncEntityMixin(TimestampMixin):
    """Общая часть сущности, привязанной к агрегату покупателя."""

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    abstract_customer_id = Column(
        BigInteger,
        ForeignKey("abstract_customer.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Полный JSON хранится для совместимости с существующими читателями.
    data = Column(JSONB, nullable=False, default=dict)
    # Токен последней синхронизации, которая видела эту строку.
    sync_run_id = Column(BigInteger, nullable=True)


class SearchableEntityMixin:
    """Поля, по которым ищут другие части системы."""

    crm_id = Column(BigInteger, nullable=True)
    login = Column(Text, nullable=True)
    name = Column(Text, nullable=True)


class AbstractCustomer(db.Model):
    """Агрегат покупателя из покупателей и сделок CRM."""

    __tablename__ = "abstract_customer"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    customers = relationship(
        "AmoCustomer", back_populates="abstract_customer",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    leads = relationship(
        "AmoLead", back_populates="abstract_customer",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    contacts = relationship(
        "AmoContact", back_populates="abstract_customer",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    companies = relationship(
        "AmoCompany", back_populates="abstract_customer",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    send_methods = relationship(
        "SendMethod", back_populates="abstract_customer",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class AmoCustomer(SearchableEntityMixin, SyncEntityMixin, db.Model):
    __tablename__ = "amo_customers"
    __table_args__ = (
        Index("uq_amo_customers_crm_id", "crm_id", unique=True),
        Index("ix_amo_customers_login", "login"),
        Index("ix_amo_customers_name", "name"),
        Index("ix_amo_customers_sync_run_id", "sync_run_id"),
    )

    abstract_customer = relationship("AbstractCustomer", back_populates="customers")


class AmoLead(SearchableEntityMixin, SyncEntityMixin, db.Model):
    __tablename__ = "amo_leads"
    __table_args__ = (
        Index("uq_amo_leads_crm_id", "crm_id", unique=True),
        Index("ix_amo_leads_login", "login"),
        Index("ix_amo_leads_name", "name"),
        Index("ix_amo_leads_sync_run_id", "sync_run_id"),
    )

    abstract_customer = relationship("AbstractCustomer", back_populates="leads")


class AmoContact(SearchableEntityMixin, SyncEntityMixin, db.Model):
    __tablename__ = "amo_contacts"
    __table_args__ = (
        Index("uq_amo_contacts_abstract_customer_id_crm_id", "abstract_customer_id", "crm_id", unique=True),
        Index("ix_amo_contacts_crm_id", "crm_id"),
        Index("ix_amo_contacts_name", "name"),
        Index("ix_amo_contacts_sync_run_id", "sync_run_id"),
    )

    abstract_customer = relationship("AbstractCustomer", back_populates="contacts")


class AmoCompany(SearchableEntityMixin, SyncEntityMixin, db.Model):
    __tablename__ = "amo_companies"
    __table_args__ = (
        Index("uq_amo_companies_abstract_customer_id_crm_id", "abstract_customer_id", "crm_id", unique=True),
        Index("ix_amo_companies_crm_id", "crm_id"),
        Index("ix_amo_companies_name", "name"),
        Index("ix_amo_companies_sync_run_id", "sync_run_id"),
    )

    abstract_customer = relationship("AbstractCustomer", back_populates="companies")


class SendMethod(SyncEntityMixin, db.Model):
    __tablename__ = "send_methods"
    __table_args__ = (
        Index("ix_send_methods_sync_run_id", "sync_run_id"),
    )

    type = Column(Text, nullable=True)
    value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

    abstract_customer = relationship("AbstractCustomer", back_populates="send_methods")
