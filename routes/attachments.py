"""
附件管理藍圖 — 上傳 / 下載 / 刪除
支援：PDF, Word, PPT, Excel, JPEG, PNG
"""
import os
import uuid
from flask import (Blueprint, current_app, send_from_directory,
                   abort, redirect, url_for, flash, request, jsonify)
from flask_login import login_required, current_user
from models import db, TaskAttachment, Task, TaskLog

attachments_bp = Blueprint('attachments', __name__)

# ── 允許的副檔名 ──────────────────────────────────────────────────────────────
ALLOWED_IMAGE_EXTS    = {'jpg', 'jpeg', 'png'}
ALLOWED_DOCUMENT_EXTS = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx'}
ALLOWED_ALL_EXTS      = ALLOWED_IMAGE_EXTS | ALLOWED_DOCUMENT_EXTS

MIME_MAP = {
    'jpg':  'image/jpeg',  'jpeg': 'image/jpeg',  'png': 'image/png',
    'pdf':  'application/pdf',
    'doc':  'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'ppt':  'application/vnd.ms-powerpoint',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'xls':  'application/vnd.ms-excel',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_ALL_EXTS

def _file_type(ext):
    return 'image' if ext in ALLOWED_IMAGE_EXTS else 'document'

def _save_files(files, task_id, log_id=None):
    """Save a list of FileStorage objects; return list of TaskAttachment instances."""
    upload_folder = current_app.config['UPLOAD_FOLDER']
    saved = []
    for f in files:
        if not f or not f.filename:
            continue
        original = f.filename
        if not _allowed(original):
            continue
        ext  = original.rsplit('.', 1)[1].lower()
        stored_name = f"{uuid.uuid4().hex}.{ext}"
        f.save(os.path.join(upload_folder, stored_name))
        att = TaskAttachment(
            task_id      = task_id,
            log_id       = log_id,
            filename     = stored_name,
            original_name= original,
            file_type    = _file_type(ext),
            mime_type    = MIME_MAP.get(ext, 'application/octet-stream'),
            file_size    = os.path.getsize(os.path.join(upload_folder, stored_name)),
            uploaded_by_id = current_user.id,
        )
        db.session.add(att)
        saved.append(att)
    return saved


# ── 公用函數供其他 blueprint 呼叫 ────────────────────────────────────────────
def save_attachments(files, task_id, log_id=None):
    """Called from tasks.py after task/log is created."""
    return _save_files(files, task_id, log_id)


# ── 下載 / 預覽 ───────────────────────────────────────────────────────────────
@attachments_bp.route('/<int:att_id>/download')
@login_required
def download(att_id):
    att = TaskAttachment.query.get_or_404(att_id)
    # 驗證用戶有權查看該任務
    task = Task.query.get_or_404(att.task_id)
    if not task.is_active:
        abort(404)

    upload_folder = current_app.config['UPLOAD_FOLDER']
    return send_from_directory(
        upload_folder,
        att.filename,
        download_name=att.original_name,
        as_attachment=not att.is_image   # 圖片直接預覽；文件強制下載
    )


# ── 刪除 ──────────────────────────────────────────────────────────────────────
@attachments_bp.route('/<int:att_id>/delete', methods=['POST'])
@login_required
def delete(att_id):
    att  = TaskAttachment.query.get_or_404(att_id)
    task = Task.query.get_or_404(att.task_id)

    # 只有上傳者、主管或管理員可刪除
    if not current_user.is_manager and att.uploaded_by_id != current_user.id:
        abort(403)

    # 刪除實體檔案
    upload_folder = current_app.config['UPLOAD_FOLDER']
    file_path = os.path.join(upload_folder, att.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    db.session.delete(att)
    db.session.commit()
    flash(f'附件「{att.original_name}」已刪除。', 'info')
    return redirect(url_for('tasks.view_task', task_id=att.task_id))
