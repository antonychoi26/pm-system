"""
日曆功能藍圖
- GET /calendar/          → 日曆頁面（FullCalendar）
- GET /calendar/events    → 返回 JSON 事件列表（FullCalendar 格式）

事件來源：
  1. Task.expected_done   — 事項預計完成日（紅/橙，視是否逾期）
  2. TaskTodo.due_date    — 工作步驟到期日（紫色）
  3. TaskLog.log_date     — 跟進記錄日期（灰色，點擊可看記錄）
"""
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from models import db, Task, TaskTodo, TaskTodoAssignee, TaskLog, TaskStatus, Estate, User
from routes.tasks import get_accessible_estate_ids
from datetime import date, datetime
from sqlalchemy import or_

calendar_bp = Blueprint('calendar', __name__)


# ── 頁面 ──────────────────────────────────────────────────────────────────────
@calendar_bp.route('/')
@login_required
def index():
    estate_ids = get_accessible_estate_ids()
    estates    = (Estate.query
                  .filter(Estate.id.in_(estate_ids), Estate.is_active == True)
                  .order_by(Estate.code).all())
    staff_list = User.query.filter_by(is_active=True).order_by(User.display_name).all() \
                 if current_user.is_manager else []
    return render_template('calendar/index.html',
                           estates=estates,
                           staff_list=staff_list)


# ── Events JSON API（FullCalendar 格式）───────────────────────────────────────
@calendar_bp.route('/events')
@login_required
def events():
    estate_ids = get_accessible_estate_ids()
    today      = date.today()

    # 篩選參數（與每日工作清單一致）
    f_estate   = request.args.get('estate_id',   type=int)
    f_assignee = request.args.get('assignee_id', type=int)
    # 日期範圍（FullCalendar 傳入 ISO 字串）
    range_start = request.args.get('start')
    range_end   = request.args.get('end')

    events = []

    # ── 1. 事項預計完成日（Task.expected_done）────────────────────────────────
    task_q = (Task.query
              .join(TaskStatus, Task.status_id == TaskStatus.id)
              .filter(
                  Task.is_active        == True,
                  TaskStatus.is_terminal == False,
                  Task.expected_done    != None,
                  Task.estate_id.in_(estate_ids),
              ))

    if not current_user.is_manager:
        task_q = task_q.filter(Task.assignee_id == current_user.id)
    elif f_assignee:
        task_q = task_q.filter(Task.assignee_id == f_assignee)

    if f_estate:
        task_q = task_q.filter(Task.estate_id == f_estate)

    for task in task_q.all():
        is_overdue = task.expected_done < today
        events.append({
            'id':    f'task-{task.id}',
            'title': f'📋 {task.task_number} {task.title[:40]}',
            'start': task.expected_done.isoformat(),
            'allDay': True,
            'color':  '#dc3545' if is_overdue else '#fd7e14',
            'textColor': '#fff',
            'extendedProps': {
                'type':        'task_deadline',
                'task_id':     task.id,
                'task_number': task.task_number,
                'title':       task.title,
                'estate':      task.estate.display_name,
                'category':    task.category.name_zh if task.category else '',
                'assignee':    task.assignee.display_name if task.assignee else '未指派',
                'is_overdue':  is_overdue,
                'url':         f'/tasks/{task.id}',
            }
        })

    # ── 2. 工作步驟到期日（TaskTodo.due_date）────────────────────────────────
    todo_q = (TaskTodo.query
              .join(Task,       TaskTodo.task_id  == Task.id)
              .join(TaskStatus, Task.status_id    == TaskStatus.id)
              .filter(
                  Task.is_active        == True,
                  TaskStatus.is_terminal == False,
                  TaskTodo.is_done       == False,
                  TaskTodo.due_date      != None,
                  Task.estate_id.in_(estate_ids),
              ))

    if not current_user.is_manager:
        assigned_todo_ids = [
            a.todo_id for a in
            TaskTodoAssignee.query.filter_by(user_id=current_user.id).all()
        ]
        todo_q = todo_q.filter(
            or_(
                Task.assignee_id == current_user.id,
                TaskTodo.id.in_(assigned_todo_ids),
            )
        )
    elif f_assignee:
        assigned_todo_ids = [
            a.todo_id for a in
            TaskTodoAssignee.query.filter_by(user_id=f_assignee).all()
        ]
        todo_q = todo_q.filter(
            or_(
                Task.assignee_id == f_assignee,
                TaskTodo.id.in_(assigned_todo_ids),
            )
        )

    if f_estate:
        todo_q = todo_q.filter(Task.estate_id == f_estate)

    for todo in todo_q.all():
        task = todo.task
        is_overdue = todo.due_date < today
        assignee_names = [a.user.display_name for a in todo.assignees.all()]
        events.append({
            'id':    f'todo-{todo.id}',
            'title': f'✅ {todo.title[:45]}',
            'start': todo.due_date.isoformat(),
            'allDay': True,
            'color':  '#6f42c1' if not is_overdue else '#842029',
            'textColor': '#fff',
            'extendedProps': {
                'type':         'todo_deadline',
                'todo_id':      todo.id,
                'task_id':      task.id,
                'task_number':  task.task_number,
                'title':        todo.title,
                'note':         todo.note or '',
                'priority':     todo.priority,
                'estate':       task.estate.display_name,
                'assignees':    assignee_names,
                'is_overdue':   is_overdue,
                'url':          f'/tasks/{task.id}',
            }
        })

    # ── 3. 跟進記錄日（TaskLog.log_date）─────────────────────────────────────
    log_q = (TaskLog.query
             .join(Task, TaskLog.task_id == Task.id)
             .join(TaskStatus, Task.status_id == TaskStatus.id)
             .filter(
                 Task.is_active        == True,
                 Task.estate_id.in_(estate_ids),
             ))

    if not current_user.is_manager:
        log_q = log_q.filter(Task.assignee_id == current_user.id)
    elif f_assignee:
        log_q = log_q.filter(Task.assignee_id == f_assignee)

    if f_estate:
        log_q = log_q.filter(Task.estate_id == f_estate)

    # 合併同一天同一事項的記錄（避免重複點）
    seen_log_keys = set()
    for log in log_q.all():
        key = (log.task_id, log.log_date.isoformat())
        if key in seen_log_keys:
            continue
        seen_log_keys.add(key)
        task = log.task
        events.append({
            'id':    f'log-{log.id}',
            'title': f'📝 {task.task_number}',
            'start': log.log_date.isoformat(),
            'allDay': True,
            'color':  '#6c757d',
            'textColor': '#fff',
            'extendedProps': {
                'type':        'log',
                'task_id':     task.id,
                'task_number': task.task_number,
                'task_title':  task.title,
                'estate':      task.estate.display_name,
                'content':     log.content[:120] + ('…' if len(log.content) > 120 else ''),
                'url':         f'/tasks/{task.id}',
            }
        })

    return jsonify(events)
