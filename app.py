"""
物業管理工作清單系統 - 主程式
Property Management Working List System - Main Application
"""
import os
from flask import Flask
from flask_login import LoginManager
from flask_session import Session
from models import db, User
from datetime import datetime, timedelta

def create_app():
    app = Flask(__name__)

    # ── Configuration ────────────────────────────────────────────────────────
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'pm-system-secret-2025-change-in-prod')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', f"sqlite:///{os.path.join(os.path.dirname(__file__), 'pm_system.db')}")
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['WTF_CSRF_ENABLED'] = True

    # ── Server-Side Session 設定 ──────────────────────────────────────────────
    # 用 filesystem 儲存 session，每個瀏覽器分頁有獨立 session ID
    # 解決共用電腦多分頁不同用戶互相干擾的問題
    SESSION_DIR = os.path.join(os.path.dirname(__file__), 'flask_sessions')
    os.makedirs(SESSION_DIR, exist_ok=True)
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_FILE_DIR'] = SESSION_DIR
    app.config['SESSION_PERMANENT'] = False
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
    app.config['SESSION_USE_SIGNER'] = True        # 防止篡改
    app.config['SESSION_KEY_PREFIX'] = 'pm_sess:'  # session 檔案前綴

    # ── Extensions ──────────────────────────────────────────────────────────
    db.init_app(app)
    Session(app)  # 啟用 server-side session

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '請先登入以繼續。'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ── Jinja2 globals & filters ────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        return dict(now=datetime.utcnow())

    app.jinja_env.globals['enumerate'] = enumerate

    # ── 禁止瀏覽器快取所有頁面 ──────────────────────────────────────────────
    # 共用電腦場景：防止瀏覽器快取上一位用戶的頁面內容
    @app.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    # ── Blueprints ──────────────────────────────────────────────────────────
    from routes.auth    import auth_bp
    from routes.tasks   import tasks_bp
    from routes.admin   import admin_bp
    from routes.reports import reports_bp
    from routes.dashboard import dashboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tasks_bp,     url_prefix='/tasks')
    app.register_blueprint(admin_bp,     url_prefix='/admin')
    app.register_blueprint(reports_bp,   url_prefix='/reports')
    app.register_blueprint(dashboard_bp, url_prefix='/')

    # ── Init DB & seed ──────────────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        seed_defaults()

    return app


def seed_defaults():
    """Seed default data if tables are empty."""
    from models import (Estate, TaskCategory, TaskStatus, User,
                        UserEstateAssignment)

    # ── Default Task Statuses ────────────────────────────────────────────
    if TaskStatus.query.count() == 0:
        statuses = [
            TaskStatus(name_zh='新增',   name_en='New',         color='info',    sort_order=1, is_terminal=False),
            TaskStatus(name_zh='跟進中', name_en='In Progress', color='warning', sort_order=2, is_terminal=False),
            TaskStatus(name_zh='完成',   name_en='Completed',   color='success', sort_order=3, is_terminal=False),
            TaskStatus(name_zh='已完成', name_en='Done',        color='secondary',sort_order=4, is_terminal=True),
        ]
        db.session.add_all(statuses)

    # ── Default Task Categories ──────────────────────────────────────────
    if TaskCategory.query.count() == 0:
        cats = [
            TaskCategory(name_zh='工程（Ad hoc）',    name_en='Works (Ad hoc)',     sort_order=1),
            TaskCategory(name_zh='工程（合約）',       name_en='Works (Contract)',   sort_order=2),
            TaskCategory(name_zh='投訴跟進',           name_en='Complaint Follow-up',sort_order=3),
            TaskCategory(name_zh='法團／管委會事宜',   name_en='MC Affairs',         sort_order=4),
            TaskCategory(name_zh='財務',               name_en='Finance',            sort_order=5),
            TaskCategory(name_zh='合約服務',           name_en='Contract Service',   sort_order=6),
            TaskCategory(name_zh='其他',               name_en='Others',             sort_order=7),
        ]
        db.session.add_all(cats)

    # ── Default Estates ──────────────────────────────────────────────────
    if Estate.query.count() == 0:
        estates_data = [
            ('ALS', '鴨寮街 88 號',   '88 Apliu Street'),
            ('BP',  '御林豪庭',       'The Bellevue Place'),
            ('EG',  '松柏花園',       'Evergreen Garden'),
            ('IDH', '樂悠居',         'I-Deal Home'),
            ('IH',  'I-Home',         'I-Home'),
            ('MA',  'Manhattan Avenue','Manhattan Avenue'),
            ('MC',  '邁爾豪園',       'Mayfair Gardens'),
            ('MOD', 'MOD 595',        'MOD 595'),
            ('OSL', '南里壹號',       'One South Lane'),
            ('OW',  '壹環',           'One West Kowloon'),
            ('SFT', '肇輝台 12 號',   '12 Shiu Fai Terrace'),
            ('SV',  '旭日豪庭',       'Sun View Court'),
            ('YP',  'York Place',     'York Place'),
            ('HQ',  '總部',           'Head Quarter'),
        ]
        for code, name_zh, name_en in estates_data:
            db.session.add(Estate(code=code, name_zh=name_zh, name_en=name_en))

    # ── Default Admin User ───────────────────────────────────────────────
    if User.query.count() == 0:
        admin = User(
            username='admin',
            display_name='系統管理員',
            email='admin@pm-system.local',
            role=User.ROLE_ADMIN,
            is_active=True
        )
        admin.set_password('Admin@2025')
        db.session.add(admin)

    db.session.commit()


if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port, debug=False)
