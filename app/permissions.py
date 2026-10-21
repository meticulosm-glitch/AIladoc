"""Calcolo dei permessi.

Regole
------
1. Dai ruoli Keycloak e dai gruppi locali dell'utente si ricavano i suoi *ruoli app*.
2. Il livello globale è il massimo `global_level` tra i suoi ruoli app
   (chi ha un ruolo in ADMIN_ROLES è sempre amministratore).
   Livello globale "none"  ->  pagina di accesso negato ovunque.
3. Per un documento si cerca la restrizione più vicina (il documento stesso o la
   cartella antenata più profonda che ne ha una):
   - nessuna restrizione  -> livello = livello globale
   - restrizione presente -> livello = min(livello globale, miglior voce ACL che
     corrisponde all'utente). Nessuna voce corrispondente -> nessun accesso.
   Il ruolo Keycloak fa quindi da "tetto": un lettore non diventa mai editor
   grazie a una ACL, mentre l'ACL può nascondere contenuti o renderli sola lettura.
4. Gli amministratori vedono e modificano tutto.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import settings
from .db import LEVELS, AppRole, LocalGroup, Restriction
from .storage import Node, ancestors

NONE, VIEW, EDIT, ADMIN = 0, 1, 2, 3


@dataclass
class UserCtx:
    sub: str
    username: str
    email: str
    name: str
    kc_roles: set[str] = field(default_factory=set)
    app_roles: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    global_level: int = NONE
    dev: bool = False

    @property
    def is_admin(self) -> bool:
        return self.global_level >= ADMIN

    @property
    def can_edit(self) -> bool:
        return self.global_level >= EDIT

    @property
    def display(self) -> str:
        return self.name or self.username or self.email or self.sub

    @property
    def initials(self) -> str:
        parts = [p for p in self.display.replace(".", " ").split() if p]
        return ("".join(p[0] for p in parts[:2]) or "?").upper()


def _lower(values) -> set[str]:
    return {str(v).strip().lower() for v in values if str(v).strip()}


def resolve_user(db: Session, session_user: dict) -> UserCtx:
    u = UserCtx(
        sub=session_user.get("sub", ""),
        username=session_user.get("username", ""),
        email=session_user.get("email", ""),
        name=session_user.get("name", ""),
        kc_roles=set(session_user.get("roles", [])),
        dev=bool(session_user.get("dev")),
    )
    kc = _lower(u.kc_roles)
    ids = _lower([u.username, u.email])

    groups = db.scalars(select(LocalGroup).options(selectinload(LocalGroup.members))).all()
    my_group_ids = set()
    for g in groups:
        if any(m.identifier.strip().lower() in ids for m in g.members):
            u.groups.append(g.name)
            my_group_ids.add(g.id)

    level = NONE
    roles = db.scalars(select(AppRole).options(selectinload(AppRole.groups))).all()
    for r in roles:
        has = bool(_lower(r.keycloak_roles or []) & kc) or any(g.id in my_group_ids for g in r.groups)
        if has:
            u.app_roles.append(r.name)
            level = max(level, LEVELS.get(r.global_level, NONE))
    if kc & _lower(settings.admin_roles):
        level = ADMIN
    u.global_level = level
    return u


class Perms:
    """Valutatore dei permessi per una singola richiesta."""

    def __init__(self, db: Session, user: UserCtx):
        self.user = user
        self.restrictions: dict[str, list] = {
            r.path: r.entries
            for r in db.scalars(select(Restriction).options(selectinload(Restriction.entries))).all()
        }
        self._app_roles = _lower(user.app_roles)
        self._groups = _lower(user.groups)
        self._kc = _lower(user.kc_roles)
        self._ids = _lower([user.username, user.email])

    def _matches(self, e) -> bool:
        v = (e.principal_value or "").strip().lower()
        return {
            "app_role": v in self._app_roles,
            "group": v in self._groups,
            "kc_role": v in self._kc,
            "user": v in self._ids,
        }.get(e.principal_type, False)

    def governing(self, rel: str) -> str | None:
        for a in ancestors(rel):
            if a in self.restrictions:
                return a
        return None

    def level(self, rel: str) -> int:
        g = self.user.global_level
        if g >= ADMIN:
            return EDIT
        if g <= NONE:
            return NONE
        gov = self.governing(rel)
        if gov is None:
            return min(g, EDIT)
        best = max((LEVELS.get(e.level, NONE) for e in self.restrictions[gov] if self._matches(e)), default=NONE)
        return min(g, best, EDIT)

    def can_view(self, rel: str) -> bool:
        return self.level(rel) >= VIEW

    def can_edit(self, rel: str) -> bool:
        return self.level(rel) >= EDIT

    def filter_tree(self, node: Node) -> Node | None:
        node.level = self.level(node.path)
        if not node.is_dir:
            return node if node.level >= VIEW else None
        kids = [k for c in node.children if (k := self.filter_tree(c)) is not None]
        node.children = kids
        if node.index and not self.can_view(node.index):
            node.index = None
        if node.level >= VIEW or kids or not node.path:
            return node
        return None
