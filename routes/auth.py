"""Authentication routes - Login / Logout"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User
from datetime import datetime

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # 只在 GET 請求（打開登入頁）時清除舊 session
    # POST 請求（按下登入按鈕）時不清除，否則會把剛登入的 session 清掉
    if request.method == 'GET':
        logout_user()
        session.clear()

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.check_password(password):
            user.last_login = datetime.utcnow()
            db.session.commit()
            # remember=False：關閉瀏覽器即清除 session，共用電腦更安全
            login_user(user, remember=False)
            next_page = request.args.get('next')
            flash(f'歡迎回來，{user.display_name}！', 'success')
            return redirect(next_page or url_for('dashboard.index'))
        else:
            error = '用戶名或密碼錯誤，請重試。'

    return render_template('auth/login.html', error=error)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已成功登出。', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    error = None
    success = None
    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        email        = request.form.get('email', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_pw   = request.form.get('confirm_password', '')

        if not display_name:
            error = '顯示名稱不能為空。'
        elif new_password and new_password != confirm_pw:
            error = '新密碼與確認密碼不符。'
        elif new_password and len(new_password) < 6:
            error = '密碼最少需要6個字元。'
        else:
            current_user.display_name = display_name
            current_user.email = email
            if new_password:
                current_user.set_password(new_password)
            db.session.commit()
            success = '個人資料已更新。'

    return render_template('auth/profile.html', error=error, success=success)
