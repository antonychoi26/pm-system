"""
每日工作清單藍圖
- 將所有事項內的未完成工作項目 (TaskTodo) 集中顯示
- 方案 B：員工看到「我負責的事項的所有 todo」OR「有指派給我的 todo（跨事項）」
- 有到期日的按日期分組（逾期 / 今日 / 本週 / 未來）
- 無到期日的另列一欄
- 可直接勾選完成，不需跳轉到事項詳情
- 可點擊 todo 開啟 Modal 修訂 / 多人指派
"""
from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user
from models import db, TaskTodo, TaskTodoAssignee, Task, Estate, TaskStatus, User
from routes.tasks import get_accessible_estate_ids
from datetime import date, timedelta, datetime
from sqlalchemy import or_

daily_bp = Blueprint('daily', __name__)


@daily_bp.route('/')
@login_required
def index():
    today      = date.today()
    estate_ids = get_accessible_estate_ids()

    # 篩選參數
    f_estate   = request.args.get('estate_id',   type=int)
    f_assignee = request.args.get('assignee_id', type=int)

    # ── 基礎查詢：未完成、所屬事項活躍且非終結 ─────────────────────────────
    base_q = (
        TaskTodo.query
        .join(Task,       TaskTodo.task_id  == Task.id)
        .join(TaskStatus, Task.status_id    == TaskStatus.id)
        .filter(
            Task.is_active        == True,
            TaskStatus.is_terminal == False,
            TaskTodo.is_done       == False,
            Task.estate_id.in_(estate_ids),
        )
    )

    # ── 可見性過濾 ────────────────────────────────────────────────────────────
    if not current_user.is_manager:
        # 方案 B：「我負責的事項下的 todo」 OR「直接指派給我的 todo」
        assigned_todo_ids = [
            a.todo_id for a in
            TaskTodoAssignee.query.filter_by(user_id=current_user.id).all()
        ]
        base_q = base_q.filter(
            or_(
                Task.assignee_id == current_user.id,
                TaskTodo.id.in_(assigned_todo_ids),
            )
        )
    elif f_assignee:
        # 主管篩選特定員工：事項負責人 OR 直接指派
        assigned_todo_ids = [
            a.todo_id for a in
            TaskTodoAssignee.query.filter_by(user_id=f_assignee).all()
        ]
        base_q = base_q.filter(
            or_(
                Task.assignee_id == f_assignee,
                TaskTodo.id.in_(assigned_todo_ids),
            )
        )

    # 屋苑篩選
    if f_estate:
        base_q = base_q.filter(Task.estate_id == f_estate)

    all_todos = base_q.all()

    # ── 分組 ────────────────────────────────────────────────────────────────
    overdue   = []
    due_today = []
    upcoming  = []
    future    = []
    no_date   = []

    for t in all_todos:
        if t.due_date is None:
            no_date.append(t)
        elif t.due_date < today:
            overdue.append(t)
        elif t.due_date == today:
            due_today.append(t)
        elif t.due_date <= today + timedelta(days=7):
            upcoming.append(t)
        else:
            future.append(t)

    overdue.sort(  key=lambda t: t.due_date)
    due_today.sort(key=lambda t: t.task_id)
    upcoming.sort( key=lambda t: t.due_date)
    future.sort(   key=lambda t: t.due_date)

    total_count   = len(all_todos)
    overdue_count = len(overdue)

    estates    = Estate.query.filter(Estate.id.in_(estate_ids),
                                     Estate.is_active == True).order_by(Estate.code).all()
    staff_list = User.query.filter_by(is_active=True).order_by(User.display_name).all()

    return render_template('daily/index.html',
        today=today,
        overdue=overdue,
        due_today=due_today,
        upcoming=upcoming,
        future=future,
        no_date=no_date,
        total_count=total_count,
        overdue_count=overdue_count,
        estates=estates,
        staff_list=staff_list,
        f_estate=f_estate,
        f_assignee=f_assignee,
    )


# ── AJAX：勾選完成 / 取消完成 ─────────────────────────────────────────────────
@daily_bp.route('/todo/<int:todo_id>/toggle', methods=['POST'])
@login_required
def toggle_todo(todo_id):
    todo = TaskTodo.query.get_or_404(todo_id)
    task = Task.query.get_or_404(todo.task_id)

    assignee_ids = [a.user_id for a in todo.assignees.all()]
    if not current_user.is_manager \
            and task.assignee_id != current_user.id \
            and current_user.id not in assignee_ids:
        return jsonify({'error': 'Forbidden'}), 403

    todo.is_done = not todo.is_done
    if todo.is_done:
        todo.done_at    = datetime.utcnow()
        todo.done_by_id = current_user.id
    else:
        todo.done_at    = None
        todo.done_by_id = None

    db.session.commit()
    return jsonify({'ok': True, 'is_done': todo.is_done})


# ── AJAX：編輯工作項目（含多人指派）──────────────────────────────────────────
@daily_bp.route('/todo/<int:todo_id>/edit', methods=['POST'])
@login_required
def edit_todo(todo_id):
    todo = TaskTodo.query.get_or_404(todo_id)
    task = Task.query.get_or_404(todo.task_id)

    current_assignee_ids = [a.user_id for a in todo.assignees.all()]
    if not current_user.is_manager \
            and todo.created_by_id != current_user.id \
            and current_user.id not in current_assignee_ids:
        return jsonify({'error': 'Forbidden'}), 403

    title        = request.form.get('title', '').strip()
    note         = request.form.get('note',  '').strip()
    priority     = request.form.get('priority', todo.priority)
    due_date_str = request.form.get('due_date', '')
    assignee_ids = request.form.getlist('assignee_ids', type=int)

    if not title:
        return jsonify({'error': '工作步驟描述不能為空'}), 400

    todo.title    = title
    todo.note     = note if note else None
    todo.priority = priority

    if due_date_str:
        try:
            todo.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            todo.due_date = None
    else:
        todo.due_date = None

    # Replace assignees
    TaskTodoAssignee.query.filter_by(todo_id=todo.id).delete()
    new_assignees = []
    for uid in set(assignee_ids):
        if uid:
            a = TaskTodoAssignee(todo_id=todo.id, user_id=uid)
            db.session.add(a)
            new_assignees.append(uid)

    db.session.commit()

    # Reload to get user names
    assignee_names = [
        a.user.display_name
        for a in TaskTodoAssignee.query.filter_by(todo_id=todo.id).all()
    ]

    return jsonify({
        'ok': True,
        'title':          todo.title,
        'note':           todo.note,
        'priority':       todo.priority,
        'due_date':       todo.due_date.strftime('%Y-%m-%d') if todo.due_date else None,
        'assignee_ids':   new_assignees,
        'assignee_names': assignee_names,
    })
