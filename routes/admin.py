"""Admin routes - Users, Estates, Categories, Statuses"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from models import db, User, Estate, TaskCategory, TaskStatus, UserEstateAssignment
from functools import wraps

admin_bp = Blueprint('admin', __name__)


def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_manager:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── Admin Index ───────────────────────────────────────────────────────────────
@admin_bp.route('/')
@login_required
@manager_required
def index():
    return render_template('admin/index.html')


# ════════════════════════════════════════════════════════════════
#  USERS
# ════════════════════════════════════════════════════════════════
@admin_bp.route('/users')
@login_required
@manager_required
def users():
    if current_user.is_admin:
        all_users = User.query.order_by(User.role, User.display_name).all()
    else:
        # Manager sees users in their estates
        estate_ids = current_user.assigned_estate_ids
        user_ids = db.session.query(UserEstateAssignment.user_id).filter(
            UserEstateAssignment.estate_id.in_(estate_ids),
            UserEstateAssignment.is_active == True
        ).distinct().all()
        uid_list = [u[0] for u in user_ids] + [current_user.id]
        all_users = User.query.filter(User.id.in_(uid_list)).order_by(User.role, User.display_name).all()

    return render_template('admin/users.html', users=all_users)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@manager_required
def new_user():
    estates = _get_manageable_estates()
    error = None

    if request.method == 'POST':
        username     = request.form.get('username', '').strip()
        display_name = request.form.get('display_name', '').strip()
        email        = request.form.get('email', '').strip()
        role         = request.form.get('role', User.ROLE_STAFF)
        password     = request.form.get('password', '')
        confirm_pw   = request.form.get('confirm_password', '')
        estate_ids   = request.form.getlist('estate_ids', type=int)

        # Managers cannot create admins
        if not current_user.is_admin and role == User.ROLE_ADMIN:
            error = '您沒有權限建立管理員帳戶。'
        elif not username:
            error = '用戶名不能為空。'
        elif User.query.filter_by(username=username).first():
            error = '此用戶名已被使用。'
        elif not display_name:
            error = '顯示名稱不能為空。'
        elif not password:
            error = '密碼不能為空。'
        elif password != confirm_pw:
            error = '密碼與確認密碼不符。'
        elif len(password) < 6:
            error = '密碼最少需要6個字元。'
        else:
            user = User(username=username, display_name=display_name,
                        email=email, role=role, is_active=True)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()

            for eid in estate_ids:
                db.session.add(UserEstateAssignment(user_id=user.id, estate_id=eid))

            db.session.commit()
            flash(f'用戶「{display_name}」已建立。', 'success')
            return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html',
        mode='new', user=None, error=error, estates=estates)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@manager_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    estates = _get_manageable_estates()
    assigned_ids = [a.estate_id for a in user.estate_assignments.filter_by(is_active=True).all()]
    error = None

    # Managers cannot edit admins (except themselves)
    if not current_user.is_admin and user.role == User.ROLE_ADMIN and user.id != current_user.id:
        abort(403)

    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        email        = request.form.get('email', '').strip()
        role         = request.form.get('role', user.role)
        new_password = request.form.get('new_password', '')
        confirm_pw   = request.form.get('confirm_password', '')
        estate_ids   = request.form.getlist('estate_ids', type=int)
        is_active    = bool(request.form.get('is_active'))

        if not current_user.is_admin and role == User.ROLE_ADMIN:
            error = '您沒有權限設定管理員角色。'
        elif not display_name:
            error = '顯示名稱不能為空。'
        elif new_password and new_password != confirm_pw:
            error = '新密碼與確認密碼不符。'
        elif new_password and len(new_password) < 6:
            error = '密碼最少需要6個字元。'
        else:
            user.display_name = display_name
            user.email        = email
            user.is_active    = is_active
            if current_user.is_admin:
                user.role = role
            if new_password:
                user.set_password(new_password)

            # Update estate assignments
            UserEstateAssignment.query.filter_by(user_id=user.id).delete()
            for eid in estate_ids:
                db.session.add(UserEstateAssignment(user_id=user.id, estate_id=eid))

            db.session.commit()
            flash(f'用戶「{user.display_name}」已更新。', 'success')
            return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html',
        mode='edit', user=user, error=error,
        estates=estates, assigned_ids=assigned_ids)


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('不能停用自己的帳戶。', 'danger')
    else:
        user.is_active = not user.is_active
        db.session.commit()
        state = '啟用' if user.is_active else '停用'
        flash(f'用戶「{user.display_name}」已{state}。', 'info')
    return redirect(url_for('admin.users'))


# ════════════════════════════════════════════════════════════════
#  ESTATES
# ════════════════════════════════════════════════════════════════
@admin_bp.route('/estates')
@login_required
@admin_required
def estates():
    all_estates = Estate.query.order_by(Estate.code).all()
    return render_template('admin/estates.html', estates=all_estates)


@admin_bp.route('/estates/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_estate():
    error = None
    if request.method == 'POST':
        code    = request.form.get('code', '').strip().upper()
        name_zh = request.form.get('name_zh', '').strip()
        name_en = request.form.get('name_en', '').strip()

        if not code:
            error = '屋苑代碼不能為空。'
        elif Estate.query.filter_by(code=code).first():
            error = '此屋苑代碼已被使用。'
        elif not name_zh:
            error = '屋苑中文名稱不能為空。'
        else:
            db.session.add(Estate(code=code, name_zh=name_zh, name_en=name_en))
            db.session.commit()
            flash(f'屋苑「{code} {name_zh}」已建立。', 'success')
            return redirect(url_for('admin.estates'))

    return render_template('admin/estate_form.html', mode='new', estate=None, error=error)


@admin_bp.route('/estates/<int:estate_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_estate(estate_id):
    estate = Estate.query.get_or_404(estate_id)
    error = None
    if request.method == 'POST':
        name_zh   = request.form.get('name_zh', '').strip()
        name_en   = request.form.get('name_en', '').strip()
        is_active = bool(request.form.get('is_active'))
        if not name_zh:
            error = '屋苑中文名稱不能為空。'
        else:
            estate.name_zh   = name_zh
            estate.name_en   = name_en
            estate.is_active = is_active
            db.session.commit()
            flash('屋苑資料已更新。', 'success')
            return redirect(url_for('admin.estates'))
    return render_template('admin/estate_form.html', mode='edit', estate=estate, error=error)


# ════════════════════════════════════════════════════════════════
#  CATEGORIES
# ════════════════════════════════════════════════════════════════
@admin_bp.route('/categories')
@login_required
@manager_required
def categories():
    cats = TaskCategory.query.order_by(TaskCategory.sort_order).all()
    return render_template('admin/categories.html', categories=cats)


@admin_bp.route('/categories/save', methods=['POST'])
@login_required
@manager_required
def save_category():
    cat_id  = request.form.get('cat_id', type=int)
    name_zh = request.form.get('name_zh', '').strip()
    name_en = request.form.get('name_en', '').strip()

    if not name_zh:
        flash('種類名稱不能為空。', 'danger')
        return redirect(url_for('admin.categories'))

    if cat_id:
        cat = TaskCategory.query.get_or_404(cat_id)
        cat.name_zh = name_zh
        cat.name_en = name_en
        flash('事項種類已更新。', 'success')
    else:
        last = TaskCategory.query.order_by(TaskCategory.sort_order.desc()).first()
        order = (last.sort_order + 1) if last else 1
        db.session.add(TaskCategory(name_zh=name_zh, name_en=name_en, sort_order=order))
        flash(f'事項種類「{name_zh}」已新增。', 'success')
    db.session.commit()
    return redirect(url_for('admin.categories'))


@admin_bp.route('/categories/<int:cat_id>/toggle', methods=['POST'])
@login_required
@manager_required
def toggle_category(cat_id):
    cat = TaskCategory.query.get_or_404(cat_id)
    cat.is_active = not cat.is_active
    db.session.commit()
    state = '啟用' if cat.is_active else '停用'
    flash(f'事項種類「{cat.name_zh}」已{state}。', 'info')
    return redirect(url_for('admin.categories'))


# ════════════════════════════════════════════════════════════════
#  STATUSES
# ════════════════════════════════════════════════════════════════
@admin_bp.route('/statuses')
@login_required
@manager_required
def statuses():
    all_statuses = TaskStatus.query.order_by(TaskStatus.sort_order).all()
    return render_template('admin/statuses.html', statuses=all_statuses)


@admin_bp.route('/statuses/save', methods=['POST'])
@login_required
@manager_required
def save_status():
    status_id  = request.form.get('status_id', type=int)
    name_zh    = request.form.get('name_zh', '').strip()
    name_en    = request.form.get('name_en', '').strip()
    color      = request.form.get('color', 'secondary')
    is_terminal= bool(request.form.get('is_terminal'))

    if not name_zh:
        flash('狀況名稱不能為空。', 'danger')
        return redirect(url_for('admin.statuses'))

    if status_id:
        s = TaskStatus.query.get_or_404(status_id)
        s.name_zh = name_zh
        s.name_en = name_en
        s.color   = color
        s.is_terminal = is_terminal
        flash('事項狀況已更新。', 'success')
    else:
        last = TaskStatus.query.order_by(TaskStatus.sort_order.desc()).first()
        order = (last.sort_order + 1) if last else 1
        db.session.add(TaskStatus(name_zh=name_zh, name_en=name_en,
                                   color=color, sort_order=order,
                                   is_terminal=is_terminal))
        flash(f'事項狀況「{name_zh}」已新增。', 'success')
    db.session.commit()
    return redirect(url_for('admin.statuses'))


@admin_bp.route('/statuses/<int:status_id>/toggle', methods=['POST'])
@login_required
@manager_required
def toggle_status(status_id):
    s = TaskStatus.query.get_or_404(status_id)
    s.is_active = not s.is_active
    db.session.commit()
    state = '啟用' if s.is_active else '停用'
    flash(f'事項狀況「{s.name_zh}」已{state}。', 'info')
    return redirect(url_for('admin.statuses'))


# ── Helper ────────────────────────────────────────────────────────────────────
def _get_manageable_estates():
    if current_user.is_admin:
        return Estate.query.filter_by(is_active=True).order_by(Estate.code).all()
    ids = current_user.assigned_estate_ids
    return Estate.query.filter(Estate.id.in_(ids), Estate.is_active == True).order_by(Estate.code).all()
