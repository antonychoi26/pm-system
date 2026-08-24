"""Notification routes - 電郵提醒功能"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from flask_mail import Message
from app import mail
from models import db, Task, TaskStatus, User
from datetime import date, timedelta
from functools import wraps

notifications_bp = Blueprint('notifications', __name__)


def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_manager:
            from flask import abort
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _get_active_status_ids():
    return [s.id for s in TaskStatus.query.filter_by(is_terminal=False, is_active=True).all()]


def _get_due_tasks(days=7):
    """取得指定天數內將到期及已逾期的事項（含負責人電郵）。"""
    today = date.today()
    due_threshold = today + timedelta(days=days)
    active_ids = _get_active_status_ids()

    # 已逾期
    overdue = Task.query.filter(
        Task.is_active == True,
        Task.status_id.in_(active_ids),
        Task.expected_done != None,
        Task.expected_done < today,
        Task.assignee_id != None,
    ).order_by(Task.expected_done.asc()).all()

    # 即將到期（今天到7天內）
    due_soon = Task.query.filter(
        Task.is_active == True,
        Task.status_id.in_(active_ids),
        Task.expected_done != None,
        Task.expected_done >= today,
        Task.expected_done <= due_threshold,
        Task.assignee_id != None,
    ).order_by(Task.expected_done.asc()).all()

    return overdue, due_soon


# ── 通知預覽頁 ────────────────────────────────────────────────────────────────
@notifications_bp.route('/')
@login_required
@manager_required
def index():
    overdue, due_soon = _get_due_tasks(days=7)
    today = date.today()
    mail_configured = bool(mail.app and mail.app.config.get('MAIL_USERNAME'))
    return render_template('notifications/index.html',
        overdue=overdue, due_soon=due_soon,
        today=today, mail_configured=mail_configured)


# ── 發送提醒電郵 ──────────────────────────────────────────────────────────────
@notifications_bp.route('/send', methods=['POST'])
@login_required
@manager_required
def send_notifications():
    send_type = request.form.get('send_type', 'all')  # all / overdue / due_soon
    overdue, due_soon = _get_due_tasks(days=7)
    today = date.today()

    if send_type == 'overdue':
        tasks_to_notify = overdue
    elif send_type == 'due_soon':
        tasks_to_notify = due_soon
    else:
        tasks_to_notify = overdue + due_soon

    if not tasks_to_notify:
        flash('沒有需要發送提醒的事項。', 'info')
        return redirect(url_for('notifications.index'))

    # 按負責人分組
    user_tasks = {}
    for task in tasks_to_notify:
        if task.assignee and task.assignee.email:
            uid = task.assignee_id
            if uid not in user_tasks:
                user_tasks[uid] = {'user': task.assignee, 'tasks': []}
            user_tasks[uid]['tasks'].append(task)

    if not user_tasks:
        flash('所有相關事項的負責人均未設定電郵地址，無法發送提醒。', 'warning')
        return redirect(url_for('notifications.index'))

    sent_count = 0
    fail_count = 0

    for uid, data in user_tasks.items():
        user = data['user']
        tasks = data['tasks']
        overdue_tasks = [t for t in tasks if t.expected_done < today]
        soon_tasks    = [t for t in tasks if t.expected_done >= today]

        try:
            subject = f'【物業管理系統】事項跟進提醒 - {today.strftime("%Y年%m月%d日")}'
            html_body = _render_email(user, overdue_tasks, soon_tasks, today)
            msg = Message(
                subject=subject,
                recipients=[user.email],
                html=html_body
            )
            mail.send(msg)
            sent_count += 1
        except Exception as e:
            fail_count += 1

    if sent_count:
        flash(f'成功發送提醒電郵予 {sent_count} 位員工。', 'success')
    if fail_count:
        flash(f'{fail_count} 封電郵發送失敗，請檢查郵件伺服器設定。', 'warning')

    return redirect(url_for('notifications.index'))


# ── 發送給單一用戶 ────────────────────────────────────────────────────────────
@notifications_bp.route('/send-user/<int:user_id>', methods=['POST'])
@login_required
@manager_required
def send_to_user(user_id):
    user = User.query.get_or_404(user_id)
    if not user.email:
        flash(f'用戶「{user.display_name}」未設定電郵地址。', 'warning')
        return redirect(url_for('notifications.index'))

    today = date.today()
    active_ids = _get_active_status_ids()
    due_threshold = today + timedelta(days=7)

    user_tasks = Task.query.filter(
        Task.is_active == True,
        Task.status_id.in_(active_ids),
        Task.expected_done != None,
        Task.expected_done <= due_threshold,
        Task.assignee_id == user_id,
    ).order_by(Task.expected_done.asc()).all()

    overdue_tasks = [t for t in user_tasks if t.expected_done < today]
    soon_tasks    = [t for t in user_tasks if t.expected_done >= today]

    if not user_tasks:
        flash(f'「{user.display_name}」沒有逾期或即將到期的事項。', 'info')
        return redirect(url_for('notifications.index'))

    try:
        subject = f'【物業管理系統】事項跟進提醒 - {today.strftime("%Y年%m月%d日")}'
        html_body = _render_email(user, overdue_tasks, soon_tasks, today)
        msg = Message(subject=subject, recipients=[user.email], html=html_body)
        mail.send(msg)
        flash(f'已成功發送提醒電郵予「{user.display_name}」（{user.email}）。', 'success')
    except Exception as e:
        flash(f'電郵發送失敗：{str(e)}', 'danger')

    return redirect(url_for('notifications.index'))


def _render_email(user, overdue_tasks, soon_tasks, today):
    """生成電郵 HTML 內容。"""
    rows_overdue = ''
    for t in overdue_tasks:
        days_late = (today - t.expected_done).days
        rows_overdue += f"""
        <tr>
          <td style="padding:8px;border:1px solid #ddd;font-family:monospace;">{t.task_number}</td>
          <td style="padding:8px;border:1px solid #ddd;">{t.estate.code if t.estate else ''}</td>
          <td style="padding:8px;border:1px solid #ddd;">{t.title}</td>
          <td style="padding:8px;border:1px solid #ddd;color:#dc3545;font-weight:bold;">
            {t.expected_done.strftime('%d/%m/%Y')}（已逾期 {days_late} 天）
          </td>
        </tr>"""

    rows_soon = ''
    for t in soon_tasks:
        days_left = (t.expected_done - today).days
        color = '#dc3545' if days_left <= 2 else '#e67e22'
        rows_soon += f"""
        <tr>
          <td style="padding:8px;border:1px solid #ddd;font-family:monospace;">{t.task_number}</td>
          <td style="padding:8px;border:1px solid #ddd;">{t.estate.code if t.estate else ''}</td>
          <td style="padding:8px;border:1px solid #ddd;">{t.title}</td>
          <td style="padding:8px;border:1px solid #ddd;color:{color};font-weight:bold;">
            {t.expected_done.strftime('%d/%m/%Y')}（還有 {days_left} 天）
          </td>
        </tr>"""

    overdue_section = ''
    if rows_overdue:
        overdue_section = f"""
        <h3 style="color:#dc3545;">⚠️ 逾期未完成事項（{len(overdue_tasks)} 項）</h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
          <thead><tr style="background:#dc3545;color:#fff;">
            <th style="padding:8px;border:1px solid #ddd;">事項編號</th>
            <th style="padding:8px;border:1px solid #ddd;">屋苑</th>
            <th style="padding:8px;border:1px solid #ddd;">事項內容</th>
            <th style="padding:8px;border:1px solid #ddd;">預計完成日期</th>
          </tr></thead>
          <tbody>{rows_overdue}</tbody>
        </table>"""

    soon_section = ''
    if rows_soon:
        soon_section = f"""
        <h3 style="color:#e67e22;">🔔 本週即將到期事項（{len(soon_tasks)} 項）</h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
          <thead><tr style="background:#e67e22;color:#fff;">
            <th style="padding:8px;border:1px solid #ddd;">事項編號</th>
            <th style="padding:8px;border:1px solid #ddd;">屋苑</th>
            <th style="padding:8px;border:1px solid #ddd;">事項內容</th>
            <th style="padding:8px;border:1px solid #ddd;">預計完成日期</th>
          </tr></thead>
          <tbody>{rows_soon}</tbody>
        </table>"""

    return f"""
    <div style="font-family:'PingFang TC','Segoe UI',sans-serif;max-width:700px;margin:0 auto;">
      <div style="background:linear-gradient(135deg,#1a3a5c,#2e86de);color:#fff;padding:20px 24px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">物業管理工作清單系統</h2>
        <p style="margin:4px 0 0;opacity:0.8;">事項跟進提醒 — {today.strftime('%Y年%m月%d日')}</p>
      </div>
      <div style="background:#f8f9fa;padding:20px 24px;border:1px solid #dee2e6;">
        <p>你好，<strong>{user.display_name}</strong>，</p>
        <p>以下是你負責的逾期及即將到期事項，請盡快跟進：</p>
        {overdue_section}
        {soon_section}
        <p style="color:#6c757d;font-size:12px;margin-top:20px;">
          此電郵由物業管理工作清單系統自動發送，請勿回覆。<br>
          如有疑問，請聯絡系統管理員。
        </p>
      </div>
    </div>"""
