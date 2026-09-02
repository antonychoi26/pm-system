"""Task management routes - CRUD + logs + filtering"""
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, abort)
from flask_login import login_required, current_user
from models import (db, Task, TaskLog, TaskStatus, TaskCategory,
                    Estate, User, generate_task_number, TaskTodo, TodoTemplate)
from datetime import datetime, date
from sqlalchemy import or_

tasks_bp = Blueprint('tasks', __name__)


def get_accessible_estate_ids():
    if current_user.is_admin:
        return [e.id for e in Estate.query.filter_by(is_active=True).all()]
    return current_user.assigned_estate_ids


def task_or_403(task_id):
    """Get task or abort 403 if no access."""
    task = Task.query.get_or_404(task_id)
    if not current_user.can_view_estate(task.estate_id):
        abort(403)
    return task


# ── List / Filter ────────────────────────────────────────────────────────────
@tasks_bp.route('/')
@login_required
def index():
    estate_ids = get_accessible_estate_ids()

    q = Task.query.filter(Task.estate_id.in_(estate_ids), Task.is_active == True)

    # ── Filters ──────────────────────────────────────────────────────
    f_estate   = request.args.get('estate_id',   type=int)
    f_status   = request.args.get('status_id',   type=int)
    f_category = request.args.get('category_id', type=int)
    f_staff    = request.args.get('assignee_id', type=int)
    f_date_from= request.args.get('date_from', '')
    f_date_to  = request.args.get('date_to', '')
    f_keyword  = request.args.get('keyword', '').strip()
    f_overdue  = request.args.get('overdue', '')
    f_view     = request.args.get('view', 'list')   # list | kanban

    if f_estate:
        if f_estate in estate_ids:
            q = q.filter(Task.estate_id == f_estate)
    if f_status:
        q = q.filter(Task.status_id == f_status)
    if f_category:
        q = q.filter(Task.category_id == f_category)
    if f_staff:
        q = q.filter(Task.assignee_id == f_staff)
    if f_date_from:
        try:
            q = q.filter(Task.created_at >= datetime.strptime(f_date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if f_date_to:
        try:
            q = q.filter(Task.created_at <= datetime.strptime(f_date_to + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
        except ValueError:
            pass
    if f_keyword:
        like = f'%{f_keyword}%'
        q = q.filter(or_(
            Task.title.ilike(like),
            Task.task_number.ilike(like),
            Task.description.ilike(like),
        ))
    if f_overdue == '1':
        today = date.today()
        terminal_ids = [s.id for s in TaskStatus.query.filter_by(is_terminal=True).all()]
        q = q.filter(
            ~Task.status_id.in_(terminal_ids),
            Task.expected_done != None,
            Task.expected_done < today
        )

    tasks = q.order_by(Task.created_at.desc()).all()

    # ── Sidebar data ──────────────────────────────────────────────────
    estates    = Estate.query.filter(Estate.id.in_(estate_ids), Estate.is_active == True).order_by(Estate.code).all()
    statuses   = TaskStatus.query.filter_by(is_active=True).order_by(TaskStatus.sort_order).all()
    categories = TaskCategory.query.filter_by(is_active=True).order_by(TaskCategory.sort_order).all()
    staff_list = User.query.filter_by(is_active=True).order_by(User.display_name).all()

    # Kanban grouping
    kanban_groups = {}
    if f_view == 'kanban':
        for s in statuses:
            kanban_groups[s] = [t for t in tasks if t.status_id == s.id]

    return render_template('tasks/index.html',
        tasks=tasks,
        estates=estates,
        statuses=statuses,
        categories=categories,
        staff_list=staff_list,
        kanban_groups=kanban_groups,
        f_estate=f_estate, f_status=f_status, f_category=f_category,
        f_staff=f_staff, f_date_from=f_date_from, f_date_to=f_date_to,
        f_keyword=f_keyword, f_overdue=f_overdue, f_view=f_view,
    )


# ── Create Task ──────────────────────────────────────────────────────────────
@tasks_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_task():
    estate_ids = get_accessible_estate_ids()
    estates    = Estate.query.filter(Estate.id.in_(estate_ids), Estate.is_active == True).order_by(Estate.code).all()
    categories = TaskCategory.query.filter_by(is_active=True).order_by(TaskCategory.sort_order).all()
    statuses   = TaskStatus.query.filter_by(is_active=True).order_by(TaskStatus.sort_order).all()
    staff_list = User.query.filter_by(is_active=True).order_by(User.display_name).all()

    error = None
    if request.method == 'POST':
        estate_id   = request.form.get('estate_id',   type=int)
        category_id = request.form.get('category_id', type=int)
        status_id   = request.form.get('status_id',   type=int)
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        assignee_id = request.form.get('assignee_id', type=int)
        expected_done_str = request.form.get('expected_done', '')
        date_added_str    = request.form.get('date_added', '')
        initial_log = request.form.get('initial_log', '').strip()
        log_date_str= request.form.get('log_date', '')

        if not estate_id or estate_id not in estate_ids:
            error = '請選擇有效屋苑。'
        elif not title:
            error = '事項內容不能為空。'
        else:
            # 使用用戶指定的新增日期，否則預設今日
            if date_added_str:
                try:
                    created_at = datetime.strptime(date_added_str, '%Y-%m-%d')
                except ValueError:
                    created_at = datetime.utcnow()
            else:
                created_at = datetime.utcnow()

            # 以事項新增日期的年份來生成編號
            year = created_at.year
            task_number = generate_task_number(estate_id, year)
            expected_done = None
            if expected_done_str:
                try:
                    expected_done = datetime.strptime(expected_done_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            task = Task(
                task_number=task_number,
                estate_id=estate_id,
                category_id=category_id,
                status_id=status_id,
                title=title,
                description=description,
                assignee_id=assignee_id,
                created_by_id=current_user.id,
                created_at=created_at,
                expected_done=expected_done,
            )
            db.session.add(task)
            db.session.flush()  # get task.id

            # Initial log entry
            if initial_log:
                log_date = date.today()
                if log_date_str:
                    try:
                        log_date = datetime.strptime(log_date_str, '%Y-%m-%d').date()
                    except ValueError:
                        pass
                log = TaskLog(
                    task_id=task.id,
                    log_date=log_date,
                    content=initial_log,
                    author_id=current_user.id,
                )
                db.session.add(log)

            db.session.commit()
            flash(f'事項 {task_number} 已成功建立。', 'success')
            return redirect(url_for('tasks.view_task', task_id=task.id))

    # Pre-fill estate from query param
    preselect_estate = request.args.get('estate_id', type=int)

    return render_template('tasks/form.html',
        mode='new', task=None, error=error,
        estates=estates, categories=categories,
        statuses=statuses, staff_list=staff_list,
        preselect_estate=preselect_estate,
        now=datetime.utcnow(),
    )


# ── View Task ────────────────────────────────────────────────────────────────
@tasks_bp.route('/<int:task_id>')
@login_required
def view_task(task_id):
    task = task_or_403(task_id)
    logs = task.logs.order_by(TaskLog.log_date.asc(), TaskLog.created_at.asc()).all()
    todos = task.todos.order_by(TaskTodo.sort_order.asc(), TaskTodo.id.asc()).all()
    templates = TodoTemplate.query.filter_by(is_active=True).order_by(TodoTemplate.name).all()
    statuses   = TaskStatus.query.filter_by(is_active=True).order_by(TaskStatus.sort_order).all()
    categories = TaskCategory.query.filter_by(is_active=True).order_by(TaskCategory.sort_order).all()
    estate_ids = get_accessible_estate_ids()
    staff_list = User.query.filter_by(is_active=True).order_by(User.display_name).all()
    return render_template('tasks/detail.html',
        task=task, logs=logs, todos=todos, templates=templates,
        statuses=statuses, categories=categories, staff_list=staff_list,
    )


# ── Edit Task ────────────────────────────────────────────────────────────────
@tasks_bp.route('/<int:task_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    task = task_or_403(task_id)
    estate_ids = get_accessible_estate_ids()
    estates    = Estate.query.filter(Estate.id.in_(estate_ids), Estate.is_active == True).order_by(Estate.code).all()
    categories = TaskCategory.query.filter_by(is_active=True).order_by(TaskCategory.sort_order).all()
    statuses   = TaskStatus.query.filter_by(is_active=True).order_by(TaskStatus.sort_order).all()
    staff_list = User.query.filter_by(is_active=True).order_by(User.display_name).all()

    # Staff can only edit tasks assigned to them
    if not current_user.is_manager and task.assignee_id != current_user.id:
        abort(403)

    error = None
    if request.method == 'POST':
        category_id = request.form.get('category_id', type=int)
        status_id   = request.form.get('status_id',   type=int)
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        assignee_id = request.form.get('assignee_id', type=int)
        expected_done_str = request.form.get('expected_done', '')

        if not title:
            error = '事項內容不能為空。'
        else:
            task.category_id  = category_id
            task.status_id    = status_id
            task.title        = title
            task.description  = description
            if current_user.is_manager:
                task.assignee_id = assignee_id
            expected_done = None
            if expected_done_str:
                try:
                    expected_done = datetime.strptime(expected_done_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            task.expected_done = expected_done

            # Auto set completed_at
            status_obj = TaskStatus.query.get(status_id)
            if status_obj and status_obj.is_terminal and not task.completed_at:
                task.completed_at = datetime.utcnow()
            elif status_obj and not status_obj.is_terminal:
                task.completed_at = None

            db.session.commit()
            flash('事項資料已更新。', 'success')
            return redirect(url_for('tasks.view_task', task_id=task.id))

    return render_template('tasks/form.html',
        mode='edit', task=task, error=error,
        estates=estates, categories=categories,
        statuses=statuses, staff_list=staff_list,
        now=datetime.utcnow(),
    )


# ── Add Log Entry ────────────────────────────────────────────────────────────
@tasks_bp.route('/<int:task_id>/log', methods=['POST'])
@login_required
def add_log(task_id):
    task = task_or_403(task_id)

    # Staff can only log on their tasks
    if not current_user.is_manager and task.assignee_id != current_user.id:
        abort(403)

    content      = request.form.get('content', '').strip()
    log_date_str = request.form.get('log_date', '')
    new_status_id= request.form.get('new_status_id', type=int)

    if not content:
        flash('跟進記錄內容不能為空。', 'danger')
        return redirect(url_for('tasks.view_task', task_id=task_id))

    log_date = date.today()
    if log_date_str:
        try:
            log_date = datetime.strptime(log_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    log = TaskLog(
        task_id=task_id,
        log_date=log_date,
        content=content,
        author_id=current_user.id,
    )
    db.session.add(log)

    # Optionally update status
    if new_status_id:
        task.status_id = new_status_id
        status_obj = TaskStatus.query.get(new_status_id)
        if status_obj and status_obj.is_terminal and not task.completed_at:
            task.completed_at = datetime.utcnow()
        elif status_obj and not status_obj.is_terminal:
            task.completed_at = None

    db.session.commit()
    flash('跟進記錄已新增。', 'success')
    return redirect(url_for('tasks.view_task', task_id=task_id))


# ── Edit Log ─────────────────────────────────────────────────────────────────
@tasks_bp.route('/log/<int:log_id>/edit', methods=['POST'])
@login_required
def edit_log(log_id):
    log  = TaskLog.query.get_or_404(log_id)
    task = task_or_403(log.task_id)

    if not current_user.is_manager and log.author_id != current_user.id:
        abort(403)

    content      = request.form.get('content', '').strip()
    log_date_str = request.form.get('log_date', '')

    if content:
        log.content = content
    if log_date_str:
        try:
            log.log_date = datetime.strptime(log_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    db.session.commit()
    flash('跟進記錄已更新。', 'success')
    return redirect(url_for('tasks.view_task', task_id=log.task_id))


# ── Delete Log ────────────────────────────────────────────────────────────────
@tasks_bp.route('/log/<int:log_id>/delete', methods=['POST'])
@login_required
def delete_log(log_id):
    log  = TaskLog.query.get_or_404(log_id)
    task = task_or_403(log.task_id)

    if not current_user.is_manager and log.author_id != current_user.id:
        abort(403)

    task_id = log.task_id
    db.session.delete(log)
    db.session.commit()
    flash('跟進記錄已刪除。', 'info')
    return redirect(url_for('tasks.view_task', task_id=task_id))


# ── Delete Task (soft) ───────────────────────────────────────────────────────
@tasks_bp.route('/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = task_or_403(task_id)
    if not current_user.is_manager:
        abort(403)
    task.is_active = False
    db.session.commit()
    flash(f'事項 {task.task_number} 已刪除。', 'info')
    return redirect(url_for('tasks.index'))


# ── Quick Status Update (AJAX) ───────────────────────────────────────────────
@tasks_bp.route('/<int:task_id>/status', methods=['POST'])
@login_required
def update_status(task_id):
    task = task_or_403(task_id)
    if not current_user.is_manager and task.assignee_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403
    status_id = request.json.get('status_id')
    if status_id:
        task.status_id = status_id
        s = TaskStatus.query.get(status_id)
        if s and s.is_terminal and not task.completed_at:
            task.completed_at = datetime.utcnow()
        elif s and not s.is_terminal:
            task.completed_at = None
        db.session.commit()
    return jsonify({'ok': True})


# ════════════════════════════════════════════════════════════════
#  TO-DO LIST ROUTES
# ════════════════════════════════════════════════════════════════

# ── Add Todo Item ─────────────────────────────────────────────────────────────
@tasks_bp.route('/<int:task_id>/todo/add', methods=['POST'])
@login_required
def todo_add(task_id):
    task = task_or_403(task_id)
    title    = request.form.get('title', '').strip()
    note     = request.form.get('note', '').strip()
    priority = request.form.get('priority', 'normal')
    due_date_str = request.form.get('due_date', '')

    if not title:
        flash('工作步驟描述不能為空。', 'danger')
        return redirect(url_for('tasks.view_task', task_id=task_id))

    # Determine next sort_order
    last = task.todos.order_by(TaskTodo.sort_order.desc()).first()
    next_order = (last.sort_order + 1) if last else 0

    due_date = None
    if due_date_str:
        try:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    todo = TaskTodo(
        task_id=task_id,
        title=title,
        note=note if note else None,
        priority=priority,
        due_date=due_date,
        sort_order=next_order,
        created_by_id=current_user.id,
    )
    db.session.add(todo)
    db.session.commit()
    flash('工作項目已新增。', 'success')
    return redirect(url_for('tasks.view_task', task_id=task_id))


# ── Toggle Todo Done/Undone (AJAX) ────────────────────────────────────────────
@tasks_bp.route('/todo/<int:todo_id>/toggle', methods=['POST'])
@login_required
def todo_toggle(todo_id):
    todo = TaskTodo.query.get_or_404(todo_id)
    task = task_or_403(todo.task_id)

    todo.is_done = not todo.is_done
    if todo.is_done:
        todo.done_at    = datetime.utcnow()
        todo.done_by_id = current_user.id
    else:
        todo.done_at    = None
        todo.done_by_id = None

    db.session.commit()

    # Return progress info for live progress bar update
    all_todos = task.todos.all()
    total = len(all_todos)
    done  = sum(1 for t in all_todos if t.is_done)
    return jsonify({
        'ok': True,
        'is_done': todo.is_done,
        'total': total,
        'done': done,
        'pct': round(done / total * 100) if total else 0,
    })


# ── Edit Todo Item ────────────────────────────────────────────────────────────
@tasks_bp.route('/todo/<int:todo_id>/edit', methods=['POST'])
@login_required
def todo_edit(todo_id):
    todo = TaskTodo.query.get_or_404(todo_id)
    task_or_403(todo.task_id)

    # Only manager, or the creator/assignee can edit
    if not current_user.is_manager and todo.created_by_id != current_user.id:
        abort(403)

    title    = request.form.get('title', '').strip()
    note     = request.form.get('note', '').strip()
    priority = request.form.get('priority', todo.priority)
    due_date_str = request.form.get('due_date', '')

    if not title:
        flash('工作步驟描述不能為空。', 'danger')
        return redirect(url_for('tasks.view_task', task_id=todo.task_id))

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

    db.session.commit()
    flash('工作項目已更新。', 'success')
    return redirect(url_for('tasks.view_task', task_id=todo.task_id))


# ── Delete Todo Item ──────────────────────────────────────────────────────────
@tasks_bp.route('/todo/<int:todo_id>/delete', methods=['POST'])
@login_required
def todo_delete(todo_id):
    todo = TaskTodo.query.get_or_404(todo_id)
    task_or_403(todo.task_id)

    if not current_user.is_manager and todo.created_by_id != current_user.id:
        abort(403)

    task_id = todo.task_id
    db.session.delete(todo)
    db.session.commit()
    flash('工作項目已刪除。', 'info')
    return redirect(url_for('tasks.view_task', task_id=task_id))


# ── Reorder Todo Items (AJAX drag-drop) ───────────────────────────────────────
@tasks_bp.route('/todo/reorder', methods=['POST'])
@login_required
def todo_reorder():
    """Expects JSON: {"order": [id1, id2, id3, ...]}"""
    data = request.get_json(force=True) or {}
    order = data.get('order', [])

    for idx, todo_id in enumerate(order):
        todo = TaskTodo.query.get(todo_id)
        if todo:
            # Basic access check: user must have estate access
            if not current_user.can_view_estate(todo.task.estate_id):
                return jsonify({'error': 'Forbidden'}), 403
            todo.sort_order = idx

    db.session.commit()
    return jsonify({'ok': True})


# ── Apply Template to Task ────────────────────────────────────────────────────
@tasks_bp.route('/<int:task_id>/todo/apply/<int:template_id>', methods=['POST'])
@login_required
def todo_apply_template(task_id, template_id):
    task     = task_or_403(task_id)
    template = TodoTemplate.query.get_or_404(template_id)

    if not template.is_active:
        flash('此範本已停用。', 'danger')
        return redirect(url_for('tasks.view_task', task_id=task_id))

    # Find current max sort_order
    last = task.todos.order_by(TaskTodo.sort_order.desc()).first()
    base_order = (last.sort_order + 1) if last else 0

    steps = template.steps.order_by('sort_order').all()
    added = 0
    for i, step in enumerate(steps):
        todo = TaskTodo(
            task_id=task_id,
            title=step.title,
            note=step.note,
            priority=step.priority,
            sort_order=base_order + i,
            created_by_id=current_user.id,
        )
        db.session.add(todo)
        added += 1

    db.session.commit()
    flash(f'已從範本「{template.name}」套用 {added} 個工作項目。', 'success')
    return redirect(url_for('tasks.view_task', task_id=task_id))
