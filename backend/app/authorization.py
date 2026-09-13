"""Trusted, default-deny role authorization for Flask API operations."""

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from flask import abort, g
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .models import AccountRole, Role

View = TypeVar("View", bound=Callable[..., Any])
_POLICY_ATTRIBUTE = "__connectsphere_role_policy__"
_AUTHENTICATED_ONLY = "authenticated-only"


def authenticated_only(view: View) -> View:
    """Mark an identity/profile operation as requiring authentication but no business role."""

    setattr(view, _POLICY_ATTRIBUTE, _AUTHENTICATED_ONLY)
    return view


def require_roles(*roles: Role) -> Callable[[View], View]:
    """Declare the roles that may execute a protected operation."""

    if not roles:
        raise ValueError("A role-protected operation must declare at least one role")
    permitted = frozenset(Role(role).value for role in roles)

    def decorate(view: View) -> View:
        @wraps(view)
        def protected(*args: Any, **kwargs: Any):
            return view(*args, **kwargs)

        setattr(protected, _POLICY_ATTRIBUTE, permitted)
        return cast(View, protected)

    return decorate


def associate_account_roles(engine: Any, view: Callable[..., Any] | None) -> None:
    """Load server-owned roles and enforce the operation's explicit policy."""

    try:
        with Session(engine) as session:
            roles = frozenset(
                session.scalars(
                    select(AccountRole.role).where(AccountRole.account_id == g.user_id)
                ).all()
            )
    except SQLAlchemyError:
        abort(503, "Authorization service unavailable.")

    g.account_roles = roles
    policy = getattr(view, _POLICY_ATTRIBUTE, None)
    if policy == _AUTHENTICATED_ONLY:
        return
    if not isinstance(policy, frozenset) or not roles.intersection(policy):
        abort(403, "Access denied.")
