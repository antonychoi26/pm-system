"""
物業管理工作清單系統 - 數據模型
Property Management Working List System - Database Models
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

# ─── 屋苑/物業 Estate ────────────────────────────────────────────────────────
class Estate(db.Model):
    __tablename__ = 'estates'
    id          = db.Column(db.Integer, primary_key=True)
    code        = db.Column(db.String(20), unique=True, nullable=False)   # e.g. BP
    name_zh     = db.Column(db.String(100), nullable=False)               # e.g. 御林豪庭
    name_en     = db.Column(db.String(100))                               # e.g. The Bellevue Place
    is_active   = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    tasks       = db.relationship('Task', backref='estate', lazy='dynamic')
    assignments = db.relationship('UserEstateAssignment', backref='estate', lazy='dynamic')

    @property
    def display_name(self):
        if self.name_zh:
            return f"{self.code} {self.name_zh}"
        return self.code

    def __repr__(self):
        return f'<Estate {self.code}>'


# ─── 事項種類 TaskCategory ────────────────────────────────────────────────────
class TaskCategory(db.Model):
    __tablename__ = 'task_categories'
    id         = db.Column(db.Integer, primary_key=True)
    name_zh    = db.Column(db.String(100), nullable=False, unique=True)
    name_en    = db.Column(db.String(100))
    sort_order = db.Column(db.Integer, default=0)
    is_active  = db.Column(db.Boolean, default=True)

    tasks      = db.relationship('Task', backref='category', lazy='dynamic')

    def __repr__(self):
        return f'<TaskCategory {self.name_zh}>'


# ─── 事項狀況 TaskStatus ──────────────────────────────────────────────────────
class TaskStatus(db.Model):
    __tablename__ = 'task_statuses'
    id         = db.Column(db.Integer, primary_key=True)
    name_zh    = db.Column(db.String(50), nullable=False, unique=True)
    name_en    = db.Column(db.String(50))
    color      = db.Column(db.String(20), default='secondary')  # Bootstrap color class
    sort_order = db.Column(db.Integer, default=0)
    is_active  = db.Column(db.Boolean, default=True)
    # is_terminal: if True, task will NOT appear in weekly report by default
    is_terminal= db.Column(db.Boolean, default=False)

    tasks      = db.relationship('Task', backref='status_obj', lazy='dynamic')

    def __repr__(self):
        return f'<TaskStatus {self.name_zh}>'


# ─── 用戶 User ────────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    ROLE_STAFF   = 'staff'
    ROLE_MANAGER = 'manager'
    ROLE_ADMIN   = 'admin'

    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    email        = db.Column(db.String(200))
    password_hash= db.Column(db.String(256), nullable=False)
    role         = db.Column(db.String(20), nullable=False, default='staff')
    is_active    = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    last_login   = db.Column(db.DateTime)

    # Tasks this user is assigned to follow up
    assigned_tasks = db.relationship('Task', backref='assignee', lazy='dynamic',
                                     foreign_keys='Task.assignee_id')
    # Logs created by this user
    logs           = db.relationship('TaskLog', backref='author', lazy='dynamic')
    # Estate assignments (for staff & manager scope)
    estate_assignments = db.relationship('UserEstateAssignment', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    @property
    def is_manager(self):
        return self.role in (self.ROLE_MANAGER, self.ROLE_ADMIN)

    @property
    def assigned_estate_ids(self):
        """Return list of estate IDs this user is assigned to."""
        return [a.estate_id for a in self.estate_assignments.filter_by(is_active=True).all()]

    def can_view_estate(self, estate_id):
        if self.is_admin or self.role == self.ROLE_MANAGER:
            # Manager sees only their assigned estates (admin sees all)
            if self.is_admin:
                return True
            return estate_id in self.assigned_estate_ids
        return estate_id in self.assigned_estate_ids

    def __repr__(self):
        return f'<User {self.username}>'


# ─── 用戶-屋苑分配 UserEstateAssignment ──────────────────────────────────────
class UserEstateAssignment(db.Model):
    __tablename__ = 'user_estate_assignments'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    estate_id  = db.Column(db.Integer, db.ForeignKey('estates.id'), nullable=False)
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'estate_id'),)


# ─── 事項 Task ────────────────────────────────────────────────────────────────
class Task(db.Model):
    __tablename__ = 'tasks'
    id              = db.Column(db.Integer, primary_key=True)
    task_number     = db.Column(db.String(30), unique=True, nullable=False)  # e.g. 25/BP0001
    estate_id       = db.Column(db.Integer, db.ForeignKey('estates.id'), nullable=False)
    category_id     = db.Column(db.Integer, db.ForeignKey('task_categories.id'))
    status_id       = db.Column(db.Integer, db.ForeignKey('task_statuses.id'))
    title           = db.Column(db.String(500), nullable=False)           # 事項內容
    description     = db.Column(db.Text)                                  # 詳細描述
    assignee_id     = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by_id   = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)    # 事項新增日期
    expected_done   = db.Column(db.Date)                                  # 預計完成日期
    completed_at    = db.Column(db.DateTime)
    is_active       = db.Column(db.Boolean, default=True)

    logs            = db.relationship('TaskLog', backref='task',
                                      lazy='dynamic', order_by='TaskLog.log_date')
    todos           = db.relationship('TaskTodo', backref='task',
                                      lazy='dynamic', order_by='TaskTodo.sort_order',
                                      cascade='all, delete-orphan')
    created_by      = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def latest_log(self):
        return self.logs.order_by(TaskLog.log_date.desc()).first()

    @property
    def is_overdue(self):
        if self.expected_done and self.status_obj and not self.status_obj.is_terminal:
            return self.expected_done < datetime.utcnow().date()
        return False

    def __repr__(self):
        return f'<Task {self.task_number}>'


# ─── 事項跟進記錄 TaskLog ─────────────────────────────────────────────────────
class TaskLog(db.Model):
    __tablename__ = 'task_logs'
    id          = db.Column(db.Integer, primary_key=True)
    task_id     = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    log_date    = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    content     = db.Column(db.Text, nullable=False)                      # 事項跟進記錄
    author_id   = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<TaskLog {self.task_id} @ {self.log_date}>'


# ─── 工作項目 TaskTodo ────────────────────────────────────────────────────────
class TaskTodo(db.Model):
    """Each to-do item (step) belonging to a Task."""
    __tablename__ = 'task_todos'

    PRIORITY_LOW    = 'low'
    PRIORITY_NORMAL = 'normal'
    PRIORITY_HIGH   = 'high'

    id           = db.Column(db.Integer, primary_key=True)
    task_id      = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    title        = db.Column(db.String(500), nullable=False)          # 工作步驟描述
    note         = db.Column(db.Text)                                 # 備註
    sort_order   = db.Column(db.Integer, default=0)                   # 排序（可拖曳）
    is_done      = db.Column(db.Boolean, default=False)               # 已完成
    priority     = db.Column(db.String(10), default='normal')         # low/normal/high
    due_date     = db.Column(db.Date)                                 # 此步驟預計日期
    done_at      = db.Column(db.DateTime)                             # 勾選完成時間
    done_by_id   = db.Column(db.Integer, db.ForeignKey('users.id'))   # 由誰完成
    created_by_id= db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    done_by      = db.relationship('User', foreign_keys=[done_by_id])
    created_by   = db.relationship('User', foreign_keys=[created_by_id])

    def __repr__(self):
        return f'<TaskTodo {self.task_id}:{self.title[:30]}>'


# ─── 工作流程範本 TodoTemplate ────────────────────────────────────────────────
class TodoTemplate(db.Model):
    """A named checklist template that can be applied to any task."""
    __tablename__ = 'todo_templates'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)           # 範本名稱
    description = db.Column(db.Text)                                  # 範本說明
    category_id = db.Column(db.Integer, db.ForeignKey('task_categories.id'))  # 適用種類（選填）
    is_active   = db.Column(db.Boolean, default=True)
    created_by_id= db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    steps       = db.relationship('TodoTemplateStep', backref='template',
                                  lazy='dynamic', order_by='TodoTemplateStep.sort_order',
                                  cascade='all, delete-orphan')
    created_by  = db.relationship('User', foreign_keys=[created_by_id])
    category    = db.relationship('TaskCategory', foreign_keys=[category_id])

    def __repr__(self):
        return f'<TodoTemplate {self.name}>'


# ─── 範本步驟 TodoTemplateStep ────────────────────────────────────────────────
class TodoTemplateStep(db.Model):
    """One step inside a TodoTemplate."""
    __tablename__ = 'todo_template_steps'

    id          = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('todo_templates.id'), nullable=False)
    title       = db.Column(db.String(500), nullable=False)
    note        = db.Column(db.Text)
    sort_order  = db.Column(db.Integer, default=0)
    priority    = db.Column(db.String(10), default='normal')

    def __repr__(self):
        return f'<TodoTemplateStep {self.template_id}:{self.title[:30]}>'


# ─── 附件 TaskAttachment ──────────────────────────────────────────────────────
class TaskAttachment(db.Model):
    """File/photo attachments linked to a Task or a TaskLog entry."""
    __tablename__ = 'task_attachments'

    id           = db.Column(db.Integer, primary_key=True)
    task_id      = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    log_id       = db.Column(db.Integer, db.ForeignKey('task_logs.id'), nullable=True)  # None = task-level
    filename     = db.Column(db.String(300), nullable=False)   # stored filename (uuid-based)
    original_name= db.Column(db.String(300), nullable=False)   # original upload name
    file_type    = db.Column(db.String(20),  nullable=False)   # 'image' or 'document'
    mime_type    = db.Column(db.String(100))
    file_size    = db.Column(db.Integer)                       # bytes
    uploaded_by_id= db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    uploaded_by  = db.relationship('User', foreign_keys=[uploaded_by_id])
    task         = db.relationship('Task', backref=db.backref('attachments', lazy='dynamic',
                                   order_by='TaskAttachment.created_at'))
    log          = db.relationship('TaskLog', backref=db.backref('attachments', lazy='dynamic',
                                   order_by='TaskAttachment.created_at'))

    @property
    def is_image(self):
        return self.file_type == 'image'

    @property
    def ext(self):
        return self.original_name.rsplit('.', 1)[-1].lower() if '.' in self.original_name else ''

    def __repr__(self):
        return f'<TaskAttachment {self.original_name}>'


# ─── 序號生成器 TaskNumberSequence ───────────────────────────────────────────
class TaskNumberSequence(db.Model):
    __tablename__ = 'task_number_sequences'
    id         = db.Column(db.Integer, primary_key=True)
    estate_id  = db.Column(db.Integer, db.ForeignKey('estates.id'), nullable=False)
    year       = db.Column(db.Integer, nullable=False)
    last_seq   = db.Column(db.Integer, default=0)

    __table_args__ = (db.UniqueConstraint('estate_id', 'year'),)


def generate_task_number(estate_id, year):
    """Auto-generate task number e.g. 25/BP0012"""
    seq = TaskNumberSequence.query.filter_by(estate_id=estate_id, year=year).first()
    if not seq:
        seq = TaskNumberSequence(estate_id=estate_id, year=year, last_seq=0)
        db.session.add(seq)
    seq.last_seq += 1
    estate = Estate.query.get(estate_id)
    year_short = str(year)[-2:]
    return f"{year_short}/{estate.code}{seq.last_seq:04d}"
