from flask import Flask, render_template, redirect, url_for, request, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime
import random

### DB Connectivity

app = Flask(__name__)

# Берем настройки из облака, если их нет — ставим заглушки
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-123')

uri = os.environ.get('DATABASE_URL', 'sqlite:///database.db')
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri

# --- МОДЕЛИ ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    characters = db.relationship('Character', backref='owner', lazy=True)

class Character(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), default="Nameless Rebel")
    char_class = db.Column(db.String(50))
    notes = db.Column(db.Text)
    agility = db.Column(db.Integer, default=0)
    knowledge = db.Column(db.Integer, default=0)
    presence = db.Column(db.Integer, default=0)
    strength = db.Column(db.Integer, default=0)
    hp_current = db.Column(db.Integer, default=1)
    hp_max = db.Column(db.Integer, default=1)
    destiny_points = db.Column(db.Integer, default=1)
    bits = db.Column(db.Boolean, default=False)
    equipment = db.Column(db.Text, default="")

# НОВАЯ МОДЕЛЬ: Лог бросков
class GameLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    username = db.Column(db.String(150))
    message = db.Column(db.String(500))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def roll_ability():
    """Бросок 3d6 и конвертация в модификатор по правилам Borg"""
    roll = sum(random.randint(1, 6) for _ in range(3))
    if roll <= 4: return -3
    elif roll <= 6: return -2
    elif roll <= 8: return -1
    elif roll <= 12: return 0
    elif roll <= 14: return 1
    elif roll <= 16: return 2
    else: return 3

def get_class_bonus(char_class, stats):
    """
    Здесь можно настроить специфику классов.
    В Star Borg классы часто меняют правило броска (например, 3d6+2).
    Пока оставим стандарт, но ты можешь раскомментировать строки ниже.
    """
    # Пример: Боты сильные, но не очень общительные
    # if char_class == 'Bot':
    #     stats['strength'] = max(stats['strength'] + 1, 3)
    #     stats['presence'] = min(stats['presence'] - 1, -3)

# --- РОУТЫ ---

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    password = request.form.get('password')
    if User.query.filter_by(username=username).first():
        flash('Пользователь уже существует')
        return redirect(url_for('index'))
    new_user = User(username=username, password=password)
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    user = User.query.filter_by(username=username, password=password).first()
    if user:
        login_user(user)
        return redirect(url_for('dashboard'))
    flash('Неверный логин или пароль')
    return redirect(url_for('index'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)

# ОБНОВЛЕННЫЙ РОУТ: Создание персонажа (отдельная страница)
@app.route('/create_char', methods=['GET', 'POST'])
@login_required
def create_char():
    if request.method == 'POST':
        name = request.form.get('name')
        char_class = request.form.get('char_class')
        # Создаем с базовыми 1 HP, потом игрок поправит
        new_char = Character(user_id=current_user.id, name=name, char_class=char_class, hp_max=4)
        db.session.add(new_char)
        db.session.commit()
        return redirect(url_for('sheet', char_id=new_char.id))
    return render_template('create_char.html')

@app.route('/sheet/<int:char_id>', methods=['GET', 'POST'])
@login_required
def sheet(char_id):
    char = Character.query.get_or_404(char_id)
    if char.owner != current_user:
        return "Access Denied", 403

    if request.method == 'POST':
        # Сохранение всех полей
        char.name = request.form.get('name')
        char.agility = int(request.form.get('agility') or 0)
        char.knowledge = int(request.form.get('knowledge') or 0)
        char.presence = int(request.form.get('presence') or 0)
        char.strength = int(request.form.get('strength') or 0)
        char.hp_current = int(request.form.get('hp_current') or 0)
        char.hp_max = int(request.form.get('hp_max') or 0)
        char.destiny_points = int(request.form.get('destiny_points') or 0)
        char.equipment = request.form.get('equipment')
        char.notes = request.form.get('notes')
        char.bits = 'bits' in request.form
        db.session.commit()
        flash('Лист сохранен!')

    return render_template('sheet.html', char=char)

# ОБНОВЛЕННЫЙ РОУТ: Броски с записью в лог и модификаторами
@app.route('/roll_api', methods=['POST'])
@login_required
def roll_api():
    data = request.get_json()
    dice_type = data.get('dice') # d4, d20...
    modifier = int(data.get('modifier', 0)) # +1, -2...
    reason = data.get('reason', '') # 'Strength Test'

    try:
        sides = int(dice_type.lower().replace('d', ''))
        roll_val = random.randint(1, sides)
        total = roll_val + modifier

        # Формируем сообщение для чата
        msg_text = f"Rolled {dice_type}"
        if modifier != 0:
            msg_text += f"+{modifier}"
        msg_text += f" = {total} ({reason})"

        # Сохраняем в БД
        new_log = GameLog(username=current_user.username, message=msg_text)
        db.session.add(new_log)
        db.session.commit()

        return jsonify({'result': total, 'raw': roll_val})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# --- НОВЫЙ РОУТ УДАЛЕНИЯ ---
@app.route('/delete_char/<int:char_id>')
@login_required
def delete_char(char_id):
    char = Character.query.get_or_404(char_id)
    if char.owner != current_user:
        return "Access Denied", 403

    db.session.delete(char)
    db.session.commit()
    flash(f'Персонаж {char.name} удален.')
    return redirect(url_for('dashboard'))

# НОВЫЙ РОУТ: Получение лога сообщений (для автообновления)
@app.route('/get_logs')
def get_logs():
    # Берем последние 20 сообщений
    logs = GameLog.query.order_by(GameLog.timestamp.desc()).limit(20).all()
    # Возвращаем список словарей
    return jsonify([{
        'time': l.timestamp.strftime('%H:%M'),
        'user': l.username,
        'msg': l.message
    } for l in logs])

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
