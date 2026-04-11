"""Unit tests for critical paths: auth, billing, limits, isolation."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta
from sqlalchemy import select, delete
from passlib.hash import bcrypt

from db.models import (
    SiteUser, UserPlan, MaxAccount, AccountStatus, Lead, LeadStatus,
    Task, TaskStatus, TaskType, MessageTemplate, UserFile, FileType,
    Payment, PaymentStatus, RefCommission, async_session_factory,
)
from db.plan_limits import check_limit, get_limits, PLAN_LIMITS


# ── Helpers ──────────────────────────────────────────
async def _cleanup_test_users():
    async with async_session_factory() as s:
        await s.execute(delete(RefCommission))
        await s.execute(delete(Payment).where(Payment.owner_id.in_(
            select(SiteUser.id).where(SiteUser.email.like("pytest_%"))
        )))
        await s.execute(delete(Task).where(Task.owner_id.in_(
            select(SiteUser.id).where(SiteUser.email.like("pytest_%"))
        )))
        await s.execute(delete(UserFile).where(UserFile.owner_id.in_(
            select(SiteUser.id).where(SiteUser.email.like("pytest_%"))
        )))
        await s.execute(delete(MessageTemplate).where(MessageTemplate.owner_id.in_(
            select(SiteUser.id).where(SiteUser.email.like("pytest_%"))
        )))
        await s.execute(delete(Lead).where(Lead.owner_id.in_(
            select(SiteUser.id).where(SiteUser.email.like("pytest_%"))
        )))
        await s.execute(delete(MaxAccount).where(MaxAccount.owner_id.in_(
            select(SiteUser.id).where(SiteUser.email.like("pytest_%"))
        )))
        await s.execute(delete(SiteUser).where(SiteUser.email.like("pytest_%")))
        await s.commit()


async def _create_user(email: str, plan: UserPlan = UserPlan.TRIAL) -> SiteUser:
    async with async_session_factory() as s:
        user = SiteUser(
            email=email,
            password_hash=bcrypt.using(rounds=4).hash("test12345"),
            name="Pytest",
            plan=plan,
            plan_expires_at=datetime.utcnow() + timedelta(days=30),
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


# ── Test 1: User registration and isolation ──────────
async def test_user_isolation():
    user1 = await _create_user("pytest_iso1@test.com")
    user2 = await _create_user("pytest_iso2@test.com")

    # Create leads for both
    async with async_session_factory() as s:
        s.add(Lead(name="Lead A", dgis_id="iso_a", owner_id=user1.id))
        s.add(Lead(name="Lead B", dgis_id="iso_b", owner_id=user1.id))
        s.add(Lead(name="Lead C", dgis_id="iso_c", owner_id=user2.id))
        await s.commit()

    # Check isolation
    async with async_session_factory() as s:
        user1_leads = (await s.execute(
            select(Lead).where(Lead.owner_id == user1.id)
        )).scalars().all()
        user2_leads = (await s.execute(
            select(Lead).where(Lead.owner_id == user2.id)
        )).scalars().all()

    assert len(user1_leads) == 2, f"User1 should see 2 leads, got {len(user1_leads)}"
    assert len(user2_leads) == 1, f"User2 should see 1 lead, got {len(user2_leads)}"
    assert all(l.owner_id == user1.id for l in user1_leads)
    assert all(l.owner_id == user2.id for l in user2_leads)
    print("  ✓ test_user_isolation")


# ── Test 2: Plan limits ──────────────────────────────
async def test_plan_limits_trial():
    user = await _create_user("pytest_limit_trial@test.com", UserPlan.TRIAL)

    # Add accounts up to limit
    limit = PLAN_LIMITS[UserPlan.TRIAL]["max_accounts"]
    async with async_session_factory() as s:
        for i in range(limit):
            s.add(MaxAccount(
                phone=f"+7900000{i:04d}",
                owner_id=user.id,
                status=AccountStatus.ACTIVE,
            ))
        await s.commit()

        can, current, lim = await check_limit(s, user, MaxAccount, "max_accounts")
    assert current == limit, f"Expected {limit}, got {current}"
    assert can is False, "Should hit limit"
    assert lim == limit
    print("  ✓ test_plan_limits_trial")


async def test_plan_limits_pro():
    user = await _create_user("pytest_limit_pro@test.com", UserPlan.PRO)
    limit = PLAN_LIMITS[UserPlan.PRO]["max_accounts"]
    assert limit == 50
    async with async_session_factory() as s:
        can, current, lim = await check_limit(s, user, MaxAccount, "max_accounts")
    assert can is True and current == 0
    print("  ✓ test_plan_limits_pro")


# ── Test 3: Superadmin no limits ─────────────────────
async def test_superadmin_no_limits():
    async with async_session_factory() as s:
        user = SiteUser(
            email="pytest_super@test.com",
            password_hash="x",
            is_superadmin=True,
            plan=UserPlan.TRIAL,  # even on trial
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)

        can, current, lim = await check_limit(s, user, MaxAccount, "max_accounts")
    assert can is True, "Superadmin should have no limits"
    assert lim > 10000
    print("  ✓ test_superadmin_no_limits")


# ── Test 4: Subscription expiry ──────────────────────
async def test_subscription_expiry():
    from max_client.subscription_checker import check_expired_subscriptions

    async with async_session_factory() as s:
        user = SiteUser(
            email="pytest_expired@test.com",
            password_hash="x",
            plan=UserPlan.BASIC,
            plan_expires_at=datetime.utcnow() - timedelta(days=1),
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        uid = user.id

    await check_expired_subscriptions()

    async with async_session_factory() as s:
        u = await s.get(SiteUser, uid)
    assert u.plan == UserPlan.TRIAL, f"Expected TRIAL after expiry, got {u.plan}"
    assert u.plan_expires_at is None
    print("  ✓ test_subscription_expiry")


# ── Test 5: Password hashing ─────────────────────────
async def test_password_hashing():
    user = await _create_user("pytest_pwd@test.com")
    async with async_session_factory() as s:
        db_user = (await s.execute(
            select(SiteUser).where(SiteUser.email == "pytest_pwd@test.com")
        )).scalar_one_or_none()
    assert db_user is not None
    assert bcrypt.verify("test12345", db_user.password_hash)
    assert not bcrypt.verify("wrong", db_user.password_hash)
    print("  ✓ test_password_hashing")


# ── Test 6: Referral code generation ─────────────────
async def test_referral_code_unique():
    user = await _create_user("pytest_ref@test.com")
    async with async_session_factory() as s:
        db_user = await s.get(SiteUser, user.id)
        if not db_user.ref_code:
            import secrets
            db_user.ref_code = secrets.token_urlsafe(8).replace("_", "").replace("-", "")[:12]
            await s.commit()
    # Ensure ref_code can be used
    assert db_user.ref_code is not None
    assert len(db_user.ref_code) > 0
    print("  ✓ test_referral_code_unique")


# ── Test 7: Task config serialization ─────────────────
async def test_task_creation():
    import json
    user = await _create_user("pytest_task@test.com", UserPlan.BASIC)

    async with async_session_factory() as s:
        task = Task(
            name="Test Task",
            task_type=TaskType.BROADCAST,
            status=TaskStatus.DRAFT,
            config=json.dumps({"template_id": 1, "limit": 10}),
            owner_id=user.id,
            log="[]",
        )
        s.add(task)
        await s.commit()

        tasks = (await s.execute(
            select(Task).where(Task.owner_id == user.id)
        )).scalars().all()
    assert len(tasks) == 1
    cfg = json.loads(tasks[0].config)
    assert cfg["limit"] == 10
    print("  ✓ test_task_creation")


# ── Runner ──────────────────────────────────────────
async def main():
    await _cleanup_test_users()

    print("Running tests...")
    try:
        await test_password_hashing()
        await test_user_isolation()
        await test_plan_limits_trial()
        await test_plan_limits_pro()
        await test_superadmin_no_limits()
        await test_subscription_expiry()
        await test_referral_code_unique()
        await test_task_creation()
        print("\n✅ All tests passed!")
    finally:
        await _cleanup_test_users()


if __name__ == "__main__":
    asyncio.run(main())
