"""Create or rotate a dedicated user for E2E tests.

Creates e2e@maxsurge.ru (PRO, not admin) with a fresh random password.
If the user already exists, rotates the password.

Usage:
    ./venv/bin/python scripts/create_e2e_user.py
    ./venv/bin/python scripts/create_e2e_user.py --email custom@maxsurge.ru

Prints credentials to stdout — copy them into GitHub Secrets.
"""
import argparse
import asyncio
import secrets
import string
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from passlib.hash import bcrypt  # noqa: E402
from sqlalchemy import select    # noqa: E402

from db.models import SiteUser, UserPlan, async_session_factory, init_db  # noqa: E402


def _gen_password(n: int = 40) -> str:
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(n))


async def main(email: str, plan: UserPlan, expires_days: int) -> None:
    await init_db()
    password = _gen_password()
    now = datetime.utcnow()
    expires_at = now + timedelta(days=expires_days) if expires_days > 0 else None

    async with async_session_factory() as s:
        user = (await s.execute(
            select(SiteUser).where(SiteUser.email == email)
        )).scalar_one_or_none()

        action: str
        if user:
            user.password_hash = bcrypt.using(rounds=12).hash(password)
            user.is_active = True
            user.plan = plan
            user.plan_expires_at = expires_at
            await s.commit()
            action = "rotated password for"
        else:
            user = SiteUser(
                email=email,
                password_hash=bcrypt.using(rounds=12).hash(password),
                name="E2E Test User",
                plan=plan,
                plan_expires_at=expires_at,
                is_active=True,
                is_superadmin=False,
            )
            s.add(user)
            await s.commit()
            await s.refresh(user)
            action = "created"

    print()
    print("=" * 60)
    print(f"{action}: {email}")
    print(f"user_id: {user.id}")
    print(f"plan:    {plan.value}")
    if expires_at:
        print(f"expires: {expires_at.isoformat()}Z")
    else:
        print("expires: never")
    print("=" * 60)
    print()
    print("Copy into GitHub → Settings → Secrets and variables → Actions:")
    print()
    print(f"  E2E_ADMIN_EMAIL     = {email}")
    print(f"  E2E_ADMIN_PASSWORD  = {password}")
    print()
    print("⚠ This is the ONLY time this password will be shown.")
    print("⚠ If you lose it, just re-run this script to rotate.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", default="e2e@maxsurge.ru")
    ap.add_argument("--plan", default="pro", choices=["trial", "start", "basic", "pro", "lifetime"])
    ap.add_argument("--expires-days", type=int, default=3650,
                    help="days until plan expires (default 3650 ≈ 10 лет)")
    args = ap.parse_args()

    plan_enum = {
        "trial":    UserPlan.TRIAL,
        "start":    UserPlan.START,
        "basic":    UserPlan.BASIC,
        "pro":      UserPlan.PRO,
        "lifetime": UserPlan.LIFETIME,
    }[args.plan]

    asyncio.run(main(args.email, plan_enum, args.expires_days))
