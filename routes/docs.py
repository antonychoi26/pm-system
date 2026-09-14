"""
說明書路由
User Manual / Documentation Routes
"""
from flask import Blueprint, render_template
from flask_login import login_required

docs_bp = Blueprint('docs', __name__)


@docs_bp.route('/manual')
@login_required
def user_manual():
    return render_template('docs/user_manual.html')
