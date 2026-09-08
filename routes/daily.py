"""
每日工作清單藍圖
- 將所有事項內的未完成工作項目 (TaskTodo) 集中顯示
- 有到期日的按日期分組（逾期 / 今日 / 未來）
- 無到期日的另列一欄
- 可直接勾選完成，不需跳轉到事項詳情
"""
from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user
from models import db, TaskTodo, Task, Estate, TaskStatus, User
from routes.tasks import get_accessible_estate_ids
from datetime import date, timedelta, datetime
from sqlalchemy import or_

daily_bp = Blueprint('daily', __name__)


@daily_bp.route('/')
@login_required
def index():
    today = date.today()
    estate_ids = get_accessible_estate_ids()

    # 篩選參數
    f_estate  = request.args.get('estate_id', type=int)
    f_assignee = request.args.get('assignee_id', type=int)

    # 基礎查詢：未完成的工作項目，且所屬事項仍活躍、非終結狀態
    base_q = (
        TaskTodo.query
        .join(Task, TaskTodo.task_id == Task.id)
        .join(TaskStatus, Task.status_id == TaskStatus.id)
        .filter(
            Task.is_active == True,
            TaskStatus.is_terminal == False,
            TaskTodo.is_done == False,
            Task.estate_id.in_(estate_ids),
        )
    )

    # 員工只看自己負責事項的工作項目；主管可看全部（或指定員工）
    if not current_user.is_manager:
        base_q = base_q.filter(Task.assignee_id == current_user.id)
    elif f_assignee:
        base_q = base_q.filter(Task.assignee_id == f_assignee)

    # 屋苑篩選
    if f_estate:
        base_q = base_q.filter(Task.estate_id == f_estate)

    all_todos = base_q.all()

    # ── 分組 ────────────────────────────────────────────────────────────────
    overdue    = []   # due_date < today
    due_today  = []   # due_date == today
    upcoming   = []   # due_date > today（未來7天）
    future     = []   # due_date > today+7
    no_date    = []   # due_date is None

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

    # 各組按到期日排序
    overdue.sort(key=lambda t: t.due_date)
    due_today.sort(key=lambda t: t.task_id)
    upcoming.sort(key=lambda t: t.due_date)
    future.sort(key=lambda t: t.due_date)

    # 統計
    total_count   = len(all_todos)
    overdue_count = len(overdue)

    # 篩選用資料
    estates    = Estate.query.filter(Estate.id.in_(estate_ids), Estate.is_active==True).order_by(Estate.code).all()
    # staff_list for filter bar (manager only) and edit modal (all users need it for assignee dropdown)
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

    # 權限檢查
    if not current_user.is_manager and task.assignee_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    from datetime import datetime
    todo.is_done = not todo.is_done
    if todo.is_done:
        todo.done_at    = datetime.utcnow()
        todo.done_by_id = current_user.id
    else:
        todo.done_at    = None
        todo.done_by_id = None

    db.session.commit()
    return jsonify({'ok': True, 'is_done': todo.is_done})


# ── AJAX：編輯工作項目（來自每日工作清單）─────────────────────────────────────
@daily_bp.route('/todo/<int:todo_id>/edit', methods=['POST'])
@login_required
def edit_todo(todo_id):
    todo = TaskTodo.query.get_or_404(todo_id)
    task = Task.query.get_or_404(todo.task_id)

    # 權限檢查：主管、建立者或指派對象皆可編輯
    if not current_user.is_manager and todo.created_by_id != current_user.id and todo.assignee_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    title        = request.form.get('title', '').strip()
    note         = request.form.get('note', '').strip()
    priority     = request.form.get('priority', todo.priority)
    due_date_str = request.form.get('due_date', '')
    assignee_id  = request.form.get('assignee_id', type=int)

    if not title:
        return jsonify({'error': '工作步驟描述不能為空'}), 400

    todo.title       = title
    todo.note        = note if note else None
    todo.priority    = priority
    todo.assignee_id = assignee_id if assignee_id else None

    if due_date_str:
        try:
            todo.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            todo.due_date = None
    else:
        todo.due_date = None

    db.session.commit()

    assignee_name = todo.assignee.display_name if todo.assignee else None
    return jsonify({
        'ok': True,
        'title': todo.title,
        'note': todo.note,
        'priority': todo.priority,
        'due_date': todo.due_date.strftime('%Y-%m-%d') if todo.due_date else None,
        'assignee_name': assignee_name,
    })
