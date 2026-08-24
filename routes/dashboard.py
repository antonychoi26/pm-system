"""Dashboard routes"""
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from models import db, Task, TaskStatus, Estate, User, TaskLog
from sqlalchemy import func, and_
from datetime import date, timedelta

dashboard_bp = Blueprint('dashboard', __name__)


def get_accessible_estates():
    """Return estates the current user can access."""
    if current_user.is_admin:
        return Estate.query.filter_by(is_active=True).order_by(Estate.code).all()
    ids = current_user.assigned_estate_ids
    return Estate.query.filter(Estate.id.in_(ids), Estate.is_active == True).order_by(Estate.code).all()


def get_base_task_query():
    """Return base task query scoped to current user's estates."""
    q = Task.query.filter_by(is_active=True)
    if not current_user.is_admin:
        ids = current_user.assigned_estate_ids
        q = q.filter(Task.estate_id.in_(ids))
    return q


@dashboard_bp.route('/')
@login_required
def index():
    today = date.today()
    overdue_threshold = today

    # ── Terminal statuses (hidden from active counts) ──────────────────
    terminal_ids = [s.id for s in TaskStatus.query.filter_by(is_terminal=True).all()]
    active_status_ids = [s.id for s in TaskStatus.query.filter_by(is_terminal=False).all()]

    base_q = get_base_task_query()

    # ── Summary cards ─────────────────────────────────────────────────
    total_active   = base_q.filter(Task.status_id.in_(active_status_ids)).count()
    total_overdue  = base_q.filter(
        Task.status_id.in_(active_status_ids),
        Task.expected_done != None,
        Task.expected_done < overdue_threshold
    ).count()

    # New this week
    week_start = today - timedelta(days=today.weekday())
    new_this_week = base_q.filter(
        Task.created_at >= week_start
    ).count()

    # Completed this week
    completed_status_ids = [s.id for s in TaskStatus.query.filter(
        TaskStatus.is_terminal == False,
        TaskStatus.name_zh.in_(['完成', '已完成'])
    ).all()]
    done_this_week = base_q.filter(
        Task.status_id.in_(completed_status_ids + terminal_ids),
        Task.completed_at >= week_start
    ).count()

    # ── Per-estate breakdown ──────────────────────────────────────────
    estates = get_accessible_estates()
    estate_stats = []
    for est in estates:
        eq = Task.query.filter_by(estate_id=est.id, is_active=True)
        active_c  = eq.filter(Task.status_id.in_(active_status_ids)).count()
        overdue_c = eq.filter(
            Task.status_id.in_(active_status_ids),
            Task.expected_done != None,
            Task.expected_done < overdue_threshold
        ).count()
        estate_stats.append({
            'estate': est,
            'active': active_c,
            'overdue': overdue_c,
        })

    # ── Per-staff breakdown (manager/admin only) ──────────────────────
    staff_stats = []
    if current_user.is_manager:
        users = User.query.filter_by(is_active=True).all()
        accessible_estate_ids = [e.id for e in estates]
        for u in users:
            uq = Task.query.filter(
                Task.assignee_id == u.id,
                Task.is_active == True,
                Task.estate_id.in_(accessible_estate_ids)
            )
            active_c  = uq.filter(Task.status_id.in_(active_status_ids)).count()
            overdue_c = uq.filter(
                Task.status_id.in_(active_status_ids),
                Task.expected_done != None,
                Task.expected_done < overdue_threshold
            ).count()
            if active_c > 0 or overdue_c > 0:
                staff_stats.append({
                    'user': u,
                    'active': active_c,
                    'overdue': overdue_c,
                })
        staff_stats.sort(key=lambda x: -x['active'])

    # ── Overdue tasks list (top 10) ───────────────────────────────────
    overdue_tasks = base_q.filter(
        Task.status_id.in_(active_status_ids),
        Task.expected_done != None,
        Task.expected_done < overdue_threshold
    ).order_by(Task.expected_done.asc()).limit(10).all()

    # ── Due soon tasks (within 7 days, not yet overdue) ───────────────
    due_soon_threshold = today + timedelta(days=7)
    due_soon_tasks = base_q.filter(
        Task.status_id.in_(active_status_ids),
        Task.expected_done != None,
        Task.expected_done >= today,
        Task.expected_done <= due_soon_threshold
    ).order_by(Task.expected_done.asc()).limit(10).all()

    # ── Recent activity (last 7 logs) ─────────────────────────────────
    accessible_task_ids = [t.id for t in base_q.all()]
    recent_logs = TaskLog.query.filter(
        TaskLog.task_id.in_(accessible_task_ids)
    ).order_by(TaskLog.created_at.desc()).limit(8).all()

    # ── Status distribution for chart ────────────────────────────────
    status_dist = []
    for s in TaskStatus.query.filter_by(is_active=True).order_by(TaskStatus.sort_order).all():
        cnt = base_q.filter(Task.status_id == s.id).count()
        status_dist.append({'name': s.name_zh, 'count': cnt, 'color': s.color})

    return render_template('dashboard/index.html',
        total_active=total_active,
        total_overdue=total_overdue,
        new_this_week=new_this_week,
        done_this_week=done_this_week,
        estate_stats=estate_stats,
        staff_stats=staff_stats,
        overdue_tasks=overdue_tasks,
        due_soon_tasks=due_soon_tasks,
        recent_logs=recent_logs,
        status_dist=status_dist,
        today=today,
    )
