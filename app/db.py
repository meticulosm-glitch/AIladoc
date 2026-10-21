"""Modelli dati: ruoli app, gruppi locali, restrizioni e ACL sui documenti."""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import (
    JSON, Column, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint,
    create_engine, select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import settings

LEVELS = {"none": 0, "view": 1, "edit": 2, "admin": 3}
LEVEL_LABELS = {"none": "Nessun accesso", "view": "Lettura", "edit": "Modifica", "admin": "Amministratore"}


class Base(DeclarativeBase):
    pass


role_groups = Table(
    "role_groups",
    Base.metadata,
    Column("role_id", ForeignKey("app_roles.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("local_groups.id", ondelete="CASCADE"), primary_key=True),
)


class AppRole(Base):
    """Ruolo interno all'app.

    Un utente HA questo ruolo se possiede almeno uno dei ruoli Keycloak elencati
    oppure se è membro di almeno uno dei gruppi locali collegati.
    `global_level` è l'accesso di base che il ruolo concede a tutta l'app.
    """
    __tablename__ = "app_roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    keycloak_roles: Mapped[list] = mapped_column(JSON, default=list)
    global_level: Mapped[str] = mapped_column(String(10), default="none")
    groups: Mapped[list["LocalGroup"]] = relationship(secondary=role_groups, back_populates="roles")


class LocalGroup(Base):
    __tablename__ = "local_groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    members: Mapped[list["GroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan", order_by="GroupMember.identifier"
    )
    roles: Mapped[list[AppRole]] = relationship(secondary=role_groups, back_populates="groups")


class GroupMember(Base):
    """Membro di un gruppo locale: username o email Keycloak (case-insensitive)."""
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "identifier"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("local_groups.id", ondelete="CASCADE"))
    identifier: Mapped[str] = mapped_column(String(255))
    group: Mapped[LocalGroup] = relationship(back_populates="members")


class Restriction(Base):
    """Un percorso (file o cartella) ad accesso ristretto.

    Vale per il percorso e tutto ciò che contiene, finché un percorso più
    profondo non definisce una restrizione propria.
    """
    __tablename__ = "restrictions"
    path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    entries: Mapped[list["AclEntry"]] = relationship(
        back_populates="restriction", cascade="all, delete-orphan", order_by="AclEntry.id"
    )


PRINCIPAL_TYPES = {
    "app_role": "Ruolo app",
    "group": "Gruppo locale",
    "kc_role": "Ruolo Keycloak",
    "user": "Utente",
}


class AclEntry(Base):
    __tablename__ = "acl_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(ForeignKey("restrictions.path", ondelete="CASCADE"))
    principal_type: Mapped[str] = mapped_column(String(20))
    principal_value: Mapped[str] = mapped_column(String(255))
    level: Mapped[str] = mapped_column(String(10), default="view")
    restriction: Mapped[Restriction] = relationship(back_populates="entries")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class SecretIgnore(Base):
    """Falso positivo del controllo password: impronta del valore (mai il valore) e percorso ("*" = ovunque)."""
    __tablename__ = "secret_ignores"
    __table_args__ = (UniqueConstraint("path", "fp"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(1024))
    fp: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(120), default="")
    masked: Mapped[str] = mapped_column(String(64), default="")
    created_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))


def get_or_create_setting(key: str, factory) -> str:
    with SessionLocal() as db:
        row = db.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=factory())
            db.add(row)
            db.commit()
        return row.value


engine = None
SessionLocal: sessionmaker | None = None


def init_db() -> None:
    global engine, SessionLocal
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    kwargs = {"connect_args": {"check_same_thread": False}} if settings.db_url.startswith("sqlite") else {}
    engine = create_engine(settings.db_url, future=True, **kwargs)
    if settings.db_url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    _bootstrap()


def _bootstrap() -> None:
    """Al primo avvio crea i ruoli app di default dai ruoli Keycloak di env."""
    with SessionLocal() as db:
        if db.scalar(select(Setting).where(Setting.key == "bootstrapped")):
            return
        defaults = [
            ("Amministratori", "Gestiscono ruoli, gruppi e permessi", settings.admin_roles, "admin"),
            ("Editor", "Possono creare e modificare documenti", settings.editor_roles, "edit"),
            ("Lettori", "Possono consultare i documenti", settings.viewer_roles, "view"),
        ]
        for name, desc, roles, level in defaults:
            if roles and not db.scalar(select(AppRole).where(AppRole.name == name)):
                db.add(AppRole(name=name, description=desc, keycloak_roles=list(roles), global_level=level))
        db.add(Setting(key="bootstrapped", value=json.dumps(True)))
        db.commit()


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
