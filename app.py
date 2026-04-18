"""
╔══════════════════════════════════════════════════════════════╗
║          BrightHaven — Cloud IoT Smart Home Platform        ║
║  Flask + Firebase + MQTT + ESP32 + Three-Tier RBAC          ║
║  © 2026 Maulin K Patel                                      ║
╚══════════════════════════════════════════════════════════════╝
"""

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, Blueprint, Response, stream_with_context
)
import os, time, threading, json, secrets
from functools import wraps
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed

# Environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# Firebase Auth is now used for all authentication
from firebase_admin import auth as firebase_auth

import requests as req_lib

# MQTT Bridge
from mqtt_bridge import MQTTBridge, MQTT_AVAILABLE

# ─── RASPBERRY PI GPIO SETUP ─────────────────────────────────────────────────
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BOARD)
    GPIO.setwarnings(False)
    GPIO_AVAILABLE = True
except ImportError:
    print("[GPIO] RPi.GPIO not available — GPIO features disabled")
    GPIO_AVAILABLE = False

# ─── FLASK APP ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'brighthaven_2026_mk_secure_key')
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours


# ─── FIREBASE ─────────────────────────────────────────────────────────────────
# ─── FIREBASE ─────────────────────────────────────────────────────────────────
firebase_creds = os.getenv("FIREBASE_CREDENTIALS")

if firebase_creds:
    # Render deployment (credentials stored as env variable)
    cred_dict = json.loads(firebase_creds)
    cred = credentials.Certificate(cred_dict)
else:
    # Local development (use JSON file)
    cred = credentials.Certificate("firebase_key.json")

firebase_admin.initialize_app(cred)
db = firestore.client()

# ─── MQTT BROKER ──────────────────────────────────────────────────────────────
mqtt_bridge = MQTTBridge(
    broker=os.getenv('MQTT_BROKER', 'broker.emqx.io'),
    port=int(os.getenv('MQTT_PORT', '8883')),
    username=os.getenv('MQTT_USERNAME', ''),
    password=os.getenv('MQTT_PASSWORD', ''),
    use_tls=os.getenv('MQTT_USE_TLS', 'true').lower() == 'true'
)

# ─── BLYNK (Dual Board — ESP8266 + ESP32) ────────────────────────────────────
# Board 1: ESP8266 — BrightHaven (TMPL3wjTF3gGK), MQTT topic: brighthaven/relay/
BLYNK_ESP8266_TEMPLATE_ID = "TMPL3wjTF3gGK"
BLYNK_ESP8266_TEMPLATE_NAME = "BrightHaven"
BLYNK_TOKEN_ESP8266 = os.getenv('BLYNK_TOKEN_ESP8266', 'PMgqRecE-oaYV9i_Hqxb8q8kSEemXqRO')

# Board 2: ESP32 — BrightHaven1 (TMPL3n_dCuyOY), MQTT topic: brighthaven1/relay/
BLYNK_ESP32_TEMPLATE_ID = "TMPL3n_dCuyOY"
BLYNK_ESP32_TEMPLATE_NAME = "BrightHaven1"
BLYNK_TOKEN_ESP32 = os.getenv('BLYNK_TOKEN_ESP32', '_o11JtMRBfA3QCLcvdpw7YpHKWGpBIcp')

BLYNK_BASE = 'https://blynk.cloud/external/api'

# ─── DEVICE CONFIG ───────────────────────────────────────────────────────────
# 'board' key: 'esp8266' or 'esp32' — determines which Blynk token to use
# ESP8266 devices use MQTT topic prefix: brighthaven/relay/
# ESP32 devices  use MQTT topic prefix: brighthaven1/relay/
LEGACY_DEVICES = {
    # ── ESP8266 Board (BrightHaven, token: PMgqRecE...) ──
    'main_fan':    {'pin': 'V0',  'room': 'Main Room',  'name': 'Ceiling Fan',     'icon': 'bi-wind',             'type': 'blynk', 'board': 'esp8266'},
    'main_light':  {'pin': 'V1',  'room': 'Main Room',  'name': 'Main Light',      'icon': 'bi-lightbulb',        'type': 'blynk', 'board': 'esp8266'},
    'main_tv':     {'pin': 'V2',  'room': 'Main Room',  'name': 'Television',      'icon': 'bi-tv',              'type': 'blynk', 'board': 'esp8266'},
    'main_wifi':   {'pin': 'V3',  'room': 'Main Room',  'name': 'WiFi Router',     'icon': 'bi-wifi',             'type': 'blynk', 'board': 'esp8266'},
    'bed1_fan':    {'pin': 'V4',  'room': 'Bedroom 1',  'name': 'Fan',             'icon': 'bi-wind',             'type': 'blynk', 'board': 'esp8266'},
    'bed1_light':  {'pin': 'V5',  'room': 'Bedroom 1',  'name': 'Light',           'icon': 'bi-lightbulb',        'type': 'blynk', 'board': 'esp8266'},
    'bed1_ac':     {'pin': 'V6',  'room': 'Bedroom 1',  'name': 'Air Conditioner', 'icon': 'bi-thermometer-snow', 'type': 'blynk', 'board': 'esp8266'},
    'bed1_tv':     {'pin': 'V7',  'room': 'Bedroom 1',  'name': 'TV',              'icon': 'bi-tv',              'type': 'blynk', 'board': 'esp8266'},
    'bed1_geyser': {'pin': 'V8',  'room': 'Bedroom 1',  'name': 'Water Geyser',    'icon': 'bi-droplet-fill',     'type': 'blynk', 'board': 'esp8266'},
    # ── ESP32 Board (BrightHaven1, token: _o11JtMRBfA...) ──
    'esp32_main_fan':   {'pin': 'V0',  'room': 'Main Room',  'name': 'Main Room Fan (ESP32)',   'icon': 'bi-wind',             'type': 'blynk', 'board': 'esp32'},
    'esp32_main_light': {'pin': 'V1',  'room': 'Main Room',  'name': 'Main Room Light (ESP32)', 'icon': 'bi-lightbulb',        'type': 'blynk', 'board': 'esp32'},
    'esp32_main_tv':    {'pin': 'V2',  'room': 'Main Room',  'name': 'Main Room TV (ESP32)',    'icon': 'bi-tv',              'type': 'blynk', 'board': 'esp32'},
    'esp32_main_wifi':  {'pin': 'V3',  'room': 'Main Room',  'name': 'Main Room WiFi (ESP32)',  'icon': 'bi-wifi',             'type': 'blynk', 'board': 'esp32'},
    'esp32_bed1_fan':   {'pin': 'V4',  'room': 'Bedroom 1',  'name': 'Bedroom1 Fan (ESP32)',    'icon': 'bi-wind',             'type': 'blynk', 'board': 'esp32'},
    'esp32_bed1_light': {'pin': 'V5',  'room': 'Bedroom 1',  'name': 'Bedroom1 Light (ESP32)', 'icon': 'bi-lightbulb',        'type': 'blynk', 'board': 'esp32'},
    'esp32_bed1_ac':    {'pin': 'V6',  'room': 'Bedroom 1',  'name': 'Bedroom1 AC (ESP32)',     'icon': 'bi-thermometer-snow', 'type': 'blynk', 'board': 'esp32'},
    'esp32_bed1_tv':    {'pin': 'V7',  'room': 'Bedroom 1',  'name': 'Bedroom1 TV (ESP32)',     'icon': 'bi-tv',              'type': 'blynk', 'board': 'esp32'},
    'esp32_bed1_geyser':{'pin': 'V8',  'room': 'Bedroom 1',  'name': 'Bedroom1 Geyser (ESP32)','icon': 'bi-droplet-fill',     'type': 'blynk', 'board': 'esp32'},
}

LEGACY_ROOMS = ['Main Room', 'Bedroom 1', 'Bedroom 2', 'Bedroom 3', 'Kitchen']

# ─── GPIO CONTROLLER ─────────────────────────────────────────────────────────
class GPIOController:
    """Active-Low relay controller for Raspberry Pi GPIO pins"""

    def __init__(self):
        self._states = {}
        self._lock = threading.Lock()

    def init_pins(self):
        if not GPIO_AVAILABLE:
            return
        for dev_id, dev in LEGACY_DEVICES.items():
            if dev.get('type') == 'gpio':
                pin = dev['pin']
                try:
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
                    print(f"[GPIO] Pin {pin} ({dev['name']}) initialized — OFF")
                except Exception as e:
                    print(f"[GPIO] Pin {pin} init error: {e}")

    def set_pin(self, pin, state):
        if not GPIO_AVAILABLE:
            return False
        try:
            with self._lock:
                GPIO.output(pin, GPIO.LOW if state else GPIO.HIGH)
                self._states[pin] = state
                return True
        except Exception as e:
            print(f"[GPIO] Pin {pin} error: {e}")
            return False

    def get_pin(self, pin):
        if not GPIO_AVAILABLE:
            return False
        try:
            return GPIO.input(pin) == GPIO.LOW
        except Exception:
            return self._states.get(pin, False)

    def shutdown_all(self):
        if not GPIO_AVAILABLE:
            return
        with self._lock:
            for dev_id, dev in LEGACY_DEVICES.items():
                if dev.get('type') == 'gpio':
                    try:
                        GPIO.output(dev['pin'], GPIO.HIGH)
                        self._states[dev['pin']] = False
                    except Exception:
                        pass

gpio_ctrl = GPIOController()

# ─── BLYNK HTTP HELPERS (Dual Token) ─────────────────────────────────────────
_http = req_lib.Session()

def blynk_token_for_device(dev_key):
    """Return the correct Blynk auth token for the device's board"""
    dev = LEGACY_DEVICES.get(dev_key, {})
    board = dev.get('board', 'esp8266')
    if board == 'esp32':
        return BLYNK_TOKEN_ESP32
    return BLYNK_TOKEN_ESP8266

def blynk_get(pin, token=None):
    """Read a virtual pin from Blynk Cloud using the given token"""
    token = token or BLYNK_TOKEN_ESP8266
    if not token:
        return False
    try:
        r = _http.get(f"{BLYNK_BASE}/get", params={'token': token, 'pin': pin}, timeout=3)
        return r.status_code == 200 and r.json()[0] == '1'
    except Exception:
        return False

def blynk_set(pin, val, token=None):
    """Write a virtual pin to Blynk Cloud using the given token"""
    token = token or BLYNK_TOKEN_ESP8266
    if not token:
        return False
    try:
        r = _http.get(f"{BLYNK_BASE}/update", params={'token': token, pin: val}, timeout=3)
        return r.status_code == 200
    except Exception:
        return False

# ─── DEVICE STATE CACHE ──────────────────────────────────────────────────────
class DeviceCache:
    """Unified device state cache — combines MQTT, Blynk, and GPIO states"""

    def __init__(self):
        self._states = {k: False for k in LEGACY_DEVICES}
        self._lock = threading.Lock()
        self._last_refresh = 0
        self.CACHE_TTL = 5

    def get_all(self):
        with self._lock:
            states = dict(self._states)
            for dev_id, dev in LEGACY_DEVICES.items():
                if dev.get('type') == 'gpio':
                    states[dev_id] = gpio_ctrl.get_pin(dev['pin'])
            return states

    def get(self, device_key):
        dev = LEGACY_DEVICES.get(device_key)
        if dev and dev.get('type') == 'gpio':
            return gpio_ctrl.get_pin(dev['pin'])
        with self._lock:
            return self._states.get(device_key, False)

    def set(self, device_key, state):
        dev = LEGACY_DEVICES.get(device_key)
        if dev and dev.get('type') == 'gpio':
            gpio_ctrl.set_pin(dev['pin'], state)
        with self._lock:
            self._states[device_key] = state

    def refresh_all(self):
        def _fetch_one(item):
            key, dev = item
            if dev.get('type') == 'gpio':
                return key, gpio_ctrl.get_pin(dev['pin'])
            # Select correct Blynk token based on board
            token = blynk_token_for_device(key)
            try:
                r = _http.get(f"{BLYNK_BASE}/get", params={'token': token, 'pin': dev['pin']}, timeout=3)
                return key, (r.status_code == 200 and r.json()[0] == '1')
            except Exception:
                return key, False

        blynk_items = [(k, v) for k, v in LEGACY_DEVICES.items() if v.get('type') != 'gpio']
        results = {}
        with ThreadPoolExecutor(max_workers=24) as ex:
            futures = {ex.submit(_fetch_one, item): item for item in blynk_items}
            try:
                for f in as_completed(futures, timeout=5):
                    try:
                        k, v = f.result()
                        results[k] = v
                    except Exception:
                        pass
            except TimeoutError:
                # Some Blynk pins didn't respond in time — use partial results
                pass

        with self._lock:
            self._states.update(results)
            self._last_refresh = time.time()

    def start_background_refresh(self):
        def _loop():
            while True:
                try:
                    self.refresh_all()
                except Exception:
                    pass
                time.sleep(self.CACHE_TTL)
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        print("[Cache] Background Blynk refresh started (every 5s)")

cache = DeviceCache()

# ─── ASYNC LOG WRITER ─────────────────────────────────────────────────────────
_log_executor = ThreadPoolExecutor(max_workers=2)


# Password helpers removed - using Firebase Authentication exclusively


# ─── EMAIL HELPERS ────────────────────────────────────────────────────────────
import smtplib
from email.message import EmailMessage

SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASS = os.getenv('SMTP_PASS', '')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'maulin18203@gmail.com')

def send_email(to_email, subject, body):
    """Send an email using SMTP or fallback to console + mock logging"""
    if not SMTP_USER or not SMTP_PASS:
        print(f"\n[EMAIL MOCK] To: {to_email}\nSubject: {subject}\n{body}\n")
        return False
        
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = to_email

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send email to {to_email}: {e}")
        return False# ─── RBAC DECORATORS ──────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('home.login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    """Requires admin or super_admin role"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session or session['user']['role'] not in ('admin', 'super_admin'):
            flash('Admin access required.', 'danger')
            return redirect(url_for('home.login'))
        return f(*args, **kwargs)
    return decorated

def super_admin_required(f):
    """Requires super_admin role only"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session or session['user']['role'] != 'super_admin':
            flash('Super Admin access required.', 'danger')
            return redirect(url_for('home.login'))
        return f(*args, **kwargs)
    return decorated

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def log_action(action, device_id=None, relay=None):
    """Log an action asynchronously to Firestore"""
    if 'user' not in session:
        return
    username = session['user']['username']
    user_id = session['user']['id']
    ip_addr = request.remote_addr

    def _write():
        try:
            db.collection('logs').add({
                'username': username,
                'userId': user_id,
                'action': action,
                'deviceId': device_id,
                'relay': relay,
                'ip_address': ip_addr,
                'timestamp': datetime.now()
            })
        except Exception as e:
            print(f"[Log Error] {e}")

    _log_executor.submit(_write)

def get_room_devices(room_name):
    """Get all legacy devices in a room with current states"""
    states = cache.get_all()
    return {k: {**v, 'state': states.get(k, False)} for k, v in LEGACY_DEVICES.items() if v['room'] == room_name}

def get_all_devices_with_state():
    """Get all legacy devices with current states"""
    states = cache.get_all()
    return {k: {**v, 'state': states.get(k, False)} for k, v in LEGACY_DEVICES.items()}

def _fb_get_count(collection):
    return len(db.collection(collection).get())

def _fb_get_logs_today():
    today_start = datetime.combine(date.today(), datetime.min.time())
    return len(db.collection('logs').where(filter=FieldFilter('timestamp', '>=', today_start)).get())

def _fb_get_recent_logs(limit=10):
    return [doc.to_dict() for doc in db.collection('logs').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(limit).get()]

def get_user_homes(user_id):
    """Get all homes a user has access to"""
    try:
        perms = db.collection('permissions').where(filter=FieldFilter('userId', '==', user_id)).get()
        home_ids = list(set([p.to_dict().get('homeId') for p in perms if p.to_dict().get('homeId')]))
        homes = []
        for hid in home_ids:
            doc = db.collection('homes').document(hid).get()
            if doc.exists:
                homes.append({**doc.to_dict(), 'id': doc.id})
        return homes
    except Exception:
        return []

def get_home_rooms(home_id):
    """Get all rooms in a home"""
    try:
        docs = db.collection('rooms').where(filter=FieldFilter('homeId', '==', home_id)).order_by('order').get()
        return [{**doc.to_dict(), 'id': doc.id} for doc in docs]
    except Exception:
        return []

def get_home_devices(home_id):
    """Get all devices in a home"""
    try:
        docs = db.collection('devices').where(filter=FieldFilter('homeId', '==', home_id)).get()
        return [{**doc.to_dict(), 'id': doc.id} for doc in docs]
    except Exception:
        return []

# ═══════════════════════════════════════════════════════════════════════════════
# HOME BLUEPRINT — Public pages (login, signup, contact, forgot password)
# ═══════════════════════════════════════════════════════════════════════════════
home_bp = Blueprint('home', __name__)

@home_bp.route('/', methods=['GET', 'POST'])
@home_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        role = session['user']['role']
        if role == 'super_admin':
            return redirect(url_for('admin.dashboard'))
        elif role == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('user.dashboard'))

    if 'user' in session:
        role = session['user']['role']
        if role == 'super_admin':
            return redirect(url_for('admin.dashboard'))
        elif role == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('user.dashboard'))
            
    return render_template('login.html')

@home_bp.route('/api/sessionLogin', methods=['POST'])
def session_login():
    """Verify Firebase ID token and establish Flask session"""
    id_token = request.json.get('idToken')
    if not id_token:
        return {'status': 'error', 'message': 'No token provided'}, 400

    try:
        decoded = firebase_auth.verify_id_token(id_token)
        email = decoded.get('email')
        uid = decoded.get('uid')
        
        if not email:
            return {'status': 'error', 'message': 'Token missing email'}, 400

        # Check collections for this email
        # 1. super_admin
        sup = db.collection('super_admin').where(filter=FieldFilter('email', '==', email)).limit(1).get()
        if sup:
            res = sup[0].to_dict()
            session['user'] = {'id': sup[0].id, 'email': email, 'username': res.get('username',''), 'role': 'super_admin', 'name': res.get('full_name')}
            session.permanent = True
            return {'status': 'success', 'redirect': url_for('admin.dashboard')}

        # 2. admin
        adm = db.collection('admin').where(filter=FieldFilter('email', '==', email)).limit(1).get()
        if adm:
            res = adm[0].to_dict()
            session['user'] = {'id': adm[0].id, 'email': email, 'username': res.get('username',''), 'role': 'admin', 'name': res.get('full_name')}
            session.permanent = True
            return {'status': 'success', 'redirect': url_for('admin.dashboard')}

        # 3. users
        usr = db.collection('users').where(filter=FieldFilter('email', '==', email)).limit(1).get()
        if usr:
            res = usr[0].to_dict()
            if res.get('suspended'):
                return {'status': 'error', 'message': 'Account suspended'}, 403
            session['user'] = {'id': usr[0].id, 'email': email, 'username': res.get('username',''), 'role': 'user', 'name': res.get('full_name')}
            session.permanent = True
            return {'status': 'success', 'redirect': url_for('user.dashboard')}

        return {'status': 'error', 'message': 'User profile not found in database'}, 404

    except Exception as e:
        print(f"[Auth Error] {e}")
        return {'status': 'error', 'message': str(e)}, 401

@home_bp.route('/signup')
def signup():
    return render_template('signup.html')

@home_bp.route('/api/register', methods=['POST'])
def api_register():
    """Create user profile in Firestore after Firebase Auth signup"""
    data = request.json
    uid = data.get('uid')
    em = data.get('email')
    fn = data.get('full_name', '')
    un = data.get('username', '')
    ph = data.get('phone', '')

    if not uid or not em:
        return {'status': 'error', 'message': 'Missing data'}, 400

    # Ensure uniqueness of username
    if un and db.collection('users').where(filter=FieldFilter('username', '==', un)).limit(1).get():
        return {'status': 'error', 'message': 'Username taken'}, 400

    # Create profile
    db.collection('users').document(uid).set({
        'full_name': fn,
        'username': un,
        'email': em,
        'phone': ph,
        'suspended': False,
        'created_at': datetime.now()
    })
    return {'status': 'success'}

@home_bp.route('/logout')
def logout():
    log_action('Logout')
    session.clear()
    return redirect(url_for('home.login'))

@home_bp.route('/forgot-password')
def forgot_password():
    return render_template('forgot_password.html')

@home_bp.route('/contact', methods=['GET', 'POST'])
def contact_us():
    if request.method == 'POST':
        name = request.form.get('name', '')
        email = request.form.get('email', '')
        subj = request.form.get('subject', '')
        msg = request.form.get('message', '')
        
        # Save to Firebase
        db.collection('contact_us').add({
            'username': name,
            'email': email,
            'subject': subj,
            'message': msg,
            'timestamp': datetime.now()
        })
        
        # Send Email to Admin
        body = f"New Contact Request from BrightHaven:\n\nName: {name}\nEmail: {email}\n\nMessage:\n{msg}"
        send_email(ADMIN_EMAIL, f"Contact Form: {subj}", body)
        
        flash('Message sent successfully! We will get back to you shortly.', 'success')
    return render_template('contact_us.html')


# ═══════════════════════════════════════════════════════════════════════════════
# USER BLUEPRINT — Dashboard, rooms, profile, device control
# ═══════════════════════════════════════════════════════════════════════════════
user_bp = Blueprint('user', __name__, url_prefix='/user')

@user_bp.route('/dashboard')
@login_required
def dashboard():
    states = cache.get_all()
    on_count = sum(1 for v in states.values() if v)

    # Get user's scenes
    scenes = []
    try:
        scene_docs = db.collection('scenes').limit(10).get()
        scenes = [{**doc.to_dict(), 'id': doc.id} for doc in scene_docs]
    except Exception:
        pass

    return render_template('users/dashboard.html',
        user=session['user'],
        rooms=LEGACY_ROOMS,
        on_count=on_count,
        total=len(LEGACY_DEVICES),
        scenes=scenes
    )

@user_bp.route('/main-room')
@login_required
def main_room():
    return render_template('users/room.html', user=session['user'],
        devices=get_room_devices('Main Room'), room_name='Main Room',
        room_icon='bi-tv', room_slug='main_room')

@user_bp.route('/bedroom-1')
@login_required
def bedroom_1():
    return render_template('users/room.html', user=session['user'],
        devices=get_room_devices('Bedroom 1'), room_name='Bedroom 1',
        room_icon='bi-moon', room_slug='bedroom_1')

@user_bp.route('/bedroom-2')
@login_required
def bedroom_2():
    return render_template('users/room.html', user=session['user'],
        devices=get_room_devices('Bedroom 2'), room_name='Bedroom 2',
        room_icon='bi-moon', room_slug='bedroom_2')

@user_bp.route('/bedroom-3')
@login_required
def bedroom_3():
    return render_template('users/room.html', user=session['user'],
        devices=get_room_devices('Bedroom 3'), room_name='Bedroom 3',
        room_icon='bi-moon', room_slug='bedroom_3')

@user_bp.route('/kitchen')
@login_required
def kitchen():
    return render_template('users/room.html', user=session['user'],
        devices=get_room_devices('Kitchen'), room_name='Kitchen',
        room_icon='bi-cup-hot', room_slug='kitchen')

@user_bp.route('/main-switch')
@login_required
def main_switch():
    states = cache.get_all()
    rooms_status = {}
    for room in LEGACY_ROOMS:
        rooms_status[room] = any(states.get(k, False) for k, v in LEGACY_DEVICES.items() if v['room'] == room)
    return render_template('users/main_switch.html', user=session['user'], rooms=rooms_status)

@user_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    doc_ref = db.collection('users').document(session['user']['id'])
    doc = doc_ref.get()
    if request.method == 'POST':
        fn = request.form.get('full_name', '').strip()
        em = request.form.get('email', '').strip()
        ph = request.form.get('phone', '').strip()
        if doc.exists:
            doc_ref.update({'full_name': fn, 'email': em, 'phone': ph})
        session['user']['name'] = fn
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('user.profile'))
    raw = doc.to_dict() if doc.exists else {}
    u = {
        'id': session['user']['id'],
        'username': raw.get('username', session['user'].get('username', 'user')),
        'full_name': raw.get('full_name', session['user'].get('name', 'User')),
        'email': raw.get('email', ''),
        'phone': raw.get('phone', ''),
        'created_at': raw.get('created_at', None)
    }
    return render_template('users/profile.html', user=session['user'], profile=u)

@user_bp.route('/notifications')
@login_required
def notifications():
    try:
        docs = db.collection('notifications').where(
            filter=FieldFilter('user_id', '==', session['user']['id'])
        ).order_by('timestamp', direction=firestore.Query.DESCENDING).limit(50).get()
        notifs = [d.to_dict() for d in docs]
    except Exception:
        notifs = []
    return render_template('users/notifications.html', user=session['user'], notifications=notifs)

@user_bp.route('/reset-credentials')
@login_required
def reset_credentials():
    return render_template('users/reset_credentials.html', user=session['user'])

@user_bp.route('/search')
@login_required
def search():
    q = request.args.get('query', '').lower().strip()
    results = [{'id': k, **v} for k, v in LEGACY_DEVICES.items()
               if q in v['name'].lower() or q in v['room'].lower()]
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify([r['name'] for r in results])
    return render_template('users/search_results.html', user=session['user'], query=q, results=results)

# ─── USER API ─────────────────────────────────────────────────────────────────

@user_bp.route('/api/toggle', methods=['POST'])
@login_required
def toggle():
    data = request.get_json() or {}
    dev_key = data.get('device')
    dev = LEGACY_DEVICES.get(dev_key)
    if not dev:
        return jsonify({'ok': False, 'error': 'Unknown device'}), 404

    state = data.get('state')

    if dev.get('type') == 'gpio':
        ok = gpio_ctrl.set_pin(dev['pin'], state)
    elif dev.get('type') == 'mqtt':
        ok = mqtt_bridge.publish_command(dev_key, 0, state)
    else:
        token = blynk_token_for_device(dev_key)
        ok = blynk_set(dev['pin'], 1 if state else 0, token=token)

    if ok:
        cache.set(dev_key, bool(state))
        log_action(f"{'ON' if state else 'OFF'}: {dev['room']} - {dev['name']}", device_id=dev_key)

    return jsonify({'ok': ok})

@user_bp.route('/api/toggle-room', methods=['POST'])
@login_required
def toggle_room():
    data = request.get_json() or {}
    room = data.get('room')
    state = data.get('state')
    room_devices = [(k, v) for k, v in LEGACY_DEVICES.items() if v['room'] == room]

    def _set_one(item):
        k, d = item
        if d.get('type') == 'gpio':
            ok = gpio_ctrl.set_pin(d['pin'], state)
        elif d.get('type') == 'mqtt':
            ok = mqtt_bridge.publish_command(k, 0, state)
        else:
            token = blynk_token_for_device(k)
            ok = blynk_set(d['pin'], 1 if state else 0, token=token)
        if ok:
            cache.set(k, bool(state))
        return ok

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(_set_one, room_devices))

    log_action(f"{'ON' if state else 'OFF'}: All devices in {room}")
    return jsonify({'ok': True, 'count': len(room_devices)})

@user_bp.route('/api/toggle-all', methods=['POST'])
@login_required
def toggle_all():
    state = (request.get_json() or {}).get('state')

    def _set_one(item):
        k, d = item
        if d.get('type') == 'gpio':
            ok = gpio_ctrl.set_pin(d['pin'], state)
        elif d.get('type') == 'mqtt':
            ok = mqtt_bridge.publish_command(k, 0, state)
        else:
            token = blynk_token_for_device(k)
            ok = blynk_set(d['pin'], 1 if state else 0, token=token)
        if ok:
            cache.set(k, bool(state))
        return ok

    with ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(_set_one, LEGACY_DEVICES.items()))

    log_action(f"{'ON' if state else 'OFF'}: ALL devices")
    return jsonify({'ok': True})

@user_bp.route('/api/status')
@login_required
def device_status():
    return jsonify(cache.get_all())

@user_bp.route('/api/scene/activate', methods=['POST'])
@login_required
def activate_scene():
    """Activate a named scene — applies all device states defined in the scene"""
    data = request.get_json() or {}
    scene_id = data.get('scene_id')
    if not scene_id:
        return jsonify({'ok': False, 'error': 'No scene_id'}), 400

    try:
        doc = db.collection('scenes').document(scene_id).get()
        if not doc.exists:
            return jsonify({'ok': False, 'error': 'Scene not found'}), 404

        scene = doc.to_dict()
        actions = scene.get('actions', [])  # [{device: 'main_fan', state: true}, ...]

        for action in actions:
            dev_key = action.get('device')
            state = action.get('state', False)
            dev = LEGACY_DEVICES.get(dev_key)
            if dev:
                if dev.get('type') == 'gpio':
                    gpio_ctrl.set_pin(dev['pin'], state)
                else:
                    token = blynk_token_for_device(dev_key)
                    blynk_set(dev['pin'], 1 if state else 0, token=token)
                cache.set(dev_key, bool(state))

        log_action(f"Scene activated: {scene.get('name', 'Unknown')}")
        return jsonify({'ok': True, 'name': scene.get('name')})

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ─── SSE ENDPOINT ─────────────────────────────────────────────────────────────
@user_bp.route('/api/sse')
@login_required
def sse_stream():
    """Server-Sent Events stream for real-time device updates"""
    def generate():
        q = mqtt_bridge.subscribe_sse()
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                try:
                    event = q.get(timeout=30)
                    yield f"data: {json.dumps(event)}\n\n"
                except Exception:
                    # Send keepalive
                    yield f": keepalive\n\n"
        finally:
            mqtt_bridge.unsubscribe_sse(q)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN BLUEPRINT — Dashboard, user/device management, logs, settings
# ═══════════════════════════════════════════════════════════════════════════════
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_users = ex.submit(_fb_get_count, 'users')
        f_contacts = ex.submit(_fb_get_count, 'contact_us')
        f_logs_td = ex.submit(_fb_get_logs_today)
        f_rec_logs = ex.submit(_fb_get_recent_logs)
        users_count = f_users.result()
        contacts_count = f_contacts.result()
        logs_today = f_logs_td.result()
        recent_logs = f_rec_logs.result()

    states = cache.get_all()
    on_count = sum(1 for v in states.values() if v)

    return render_template('admin/dashboard.html',
        user=session['user'],
        users_count=users_count,
        logs_today=logs_today,
        contacts_count=contacts_count,
        recent_logs=recent_logs,
        devices_on=on_count,
        total_devices=len(LEGACY_DEVICES),
        rooms=LEGACY_ROOMS,
        mqtt_connected=mqtt_bridge.is_connected()
    )

@admin_bp.route('/users')
@admin_required
def user_management():
    users = [dict(doc.to_dict(), id=doc.id) for doc in db.collection('users').get() if not doc.to_dict().get('_init')]
    return render_template('admin/user_management.html', user=session['user'], users=users)

@admin_bp.route('/users/delete/<uid>', methods=['POST'])
@admin_required
def delete_user(uid):
    try:
        firebase_auth.delete_user(uid)
    except Exception as e:
        print(f"Error deleting from Firebase Auth: {e}")
        flash(f'Warning: Firebase Auth deletion failed ({e}).', 'warning')
    
    db.collection('users').document(uid).delete()
    log_action(f'Deleted user {uid}')
    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/create', methods=['POST'])
@admin_required
def create_user():
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    full_name = request.form.get('full_name', '').strip()
    username = request.form.get('username', '').strip()
    role = request.form.get('role', 'user')

    if not email or not password or not username:
        flash('Email, password, and username are required.', 'danger')
        return redirect(url_for('admin.user_management'))

    try:
        user = firebase_auth.create_user(
            email=email,
            password=password,
            display_name=full_name
        )
        db.collection('users').document(user.uid).set({
            'full_name': full_name,
            'username': username,
            'email': email,
            'role': role,
            'suspended': False,
            'created_at': datetime.now()
        })
        log_action(f'Created user {email} as {role}')
        flash('User created successfully.', 'success')
    except Exception as e:
        flash(f'Failed to create user: {e}', 'danger')

    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/edit/<uid>', methods=['POST'])
@admin_required
def edit_user(uid):
    full_name = request.form.get('full_name', '').strip()
    username = request.form.get('username', '').strip()
    role = request.form.get('role', 'user')

    if not username:
        flash('Username cannot be empty.', 'danger')
        return redirect(url_for('admin.user_management'))

    try:
        firebase_auth.update_user(uid, display_name=full_name)
        db.collection('users').document(uid).update({
            'full_name': full_name,
            'username': username,
            'role': role
        })
        log_action(f'Updated user {uid}')
        flash('User updated successfully.', 'success')
    except Exception as e:
        flash(f'Failed to update user: {e}', 'danger')

    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/password/<uid>', methods=['POST'])
@admin_required
def change_user_password(uid):
    new_password = request.form.get('password', '')
    if len(new_password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin.user_management'))

    try:
        firebase_auth.update_user(uid, password=new_password)
        log_action(f'Changed password for user {uid}')
        flash('User password updated successfully.', 'success')
    except Exception as e:
        flash(f'Failed to update password: {e}', 'danger')

    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/suspend/<uid>', methods=['POST'])
@admin_required
def suspend_user(uid):
    db.collection('users').document(uid).update({'suspended': True})
    log_action(f'Suspended user {uid}')
    flash('User suspended.', 'success')
    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/unsuspend/<uid>', methods=['POST'])
@admin_required
def unsuspend_user(uid):
    db.collection('users').document(uid).update({'suspended': False})
    log_action(f'Unsuspended user {uid}')
    flash('User reactivated.', 'success')
    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/invite', methods=['POST'])
@admin_required
def invite_user():
    """Invite a user by email with specific room permissions"""
    email = request.form.get('email', '').strip()
    role = request.form.get('role', 'user')
    room_ids = request.form.getlist('room_ids')

    if not email:
        flash('Email is required.', 'danger')
        return redirect(url_for('admin.user_management'))

    # Create permission record
    db.collection('permissions').add({
        'email': email,
        'role': role,
        'roomIds': room_ids,
        'homeId': session['user'].get('homeId', ''),
        'grantedBy': session['user']['id'],
        'createdAt': datetime.now(),
        'expiresAt': None
    })

    log_action(f'Invited {email} as {role}')
    flash(f'Invitation sent to {email}.', 'success')
    return redirect(url_for('admin.user_management'))

@admin_bp.route('/devices')
@admin_required
def device_management():
    status = get_all_devices_with_state()
    mqtt_devices = []
    try:
        mqtt_docs = db.collection('devices').limit(50).get()
        mqtt_devices = [{**doc.to_dict(), 'id': doc.id} for doc in mqtt_docs]
    except Exception:
        pass
    return render_template('admin/device_management.html',
        user=session['user'], devices=status, rooms=LEGACY_ROOMS,
        mqtt_devices=mqtt_devices)

@admin_bp.route('/devices/register', methods=['POST'])
@admin_required
def register_device():
    """Register a new MQTT device and link to a home/room"""
    device_id = request.form.get('device_id', '').strip()
    name = request.form.get('name', '').strip()
    room = request.form.get('room', '').strip()

    if not device_id or not name:
        flash('Device ID and name are required.', 'danger')
        return redirect(url_for('admin.device_management'))

    # Create device record
    device_secret = secrets.token_hex(16)
    db.collection('devices').document(device_id).set({
        'name': name,
        'room': room,
        'homeId': session['user'].get('homeId', 'default'),
        'roomId': '',
        'deviceSecret': device_secret,
        'status': 'offline',
        'lastSeen': None,
        'firmwareVersion': '1.0.0',
        'relayCount': 1,
        'locked': False,
        'createdAt': datetime.now()
    })

    log_action(f'Registered device {device_id}')
    flash(f'Device registered! Secret: {device_secret} — save this, it cannot be retrieved again.', 'success')
    return redirect(url_for('admin.device_management'))

@admin_bp.route('/logs')
@admin_required
def logs():
    all_logs = [doc.to_dict() for doc in
        db.collection('logs').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(500).get()]
    return render_template('admin/logs.html', user=session['user'], logs=all_logs)

@admin_bp.route('/notifications')
@admin_required
def notifications():
    contacts = [doc.to_dict() for doc in
        db.collection('contact_us').order_by('timestamp', direction=firestore.Query.DESCENDING).get()]
    return render_template('admin/notifications.html', user=session['user'], contact_requests=contacts)

@admin_bp.route('/profile', methods=['GET', 'POST'])
@admin_required
def profile():
    col = 'super_admin' if session['user']['role'] == 'super_admin' else 'admin'
    doc_ref = db.collection(col).document(session['user']['id'])
    doc = doc_ref.get()
    if request.method == 'POST':
        fn = request.form.get('full_name', '').strip()
        em = request.form.get('email', '').strip()
        if doc.exists:
            doc_ref.update({'full_name': fn, 'email': em})
        session['user']['name'] = fn
        flash('Profile updated!', 'success')
        return redirect(url_for('admin.profile'))
    # Build admin dict with safe defaults
    raw = doc.to_dict() if doc.exists else {}
    a = {
        'id': session['user']['id'],
        'username': raw.get('username', session['user'].get('username', 'admin')),
        'full_name': raw.get('full_name', session['user'].get('name', 'Admin')),
        'email': raw.get('email', ''),
        'role': raw.get('role', session['user'].get('role', 'admin')),
        'created_at': raw.get('created_at', None)
    }
    return render_template('admin/profile.html', user=session['user'], admin=a)

@admin_bp.route('/reset-credentials')
@admin_required
def reset_credentials():
    return render_template('admin/reset_credentials.html', user=session['user'])

@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    if request.method == 'POST':
        flash('Settings saved successfully.', 'success')
    s_docs = db.collection('settings').get()
    settings_data = {doc.to_dict().get('key_name'): doc.to_dict().get('value')
                     for doc in s_docs if not doc.to_dict().get('_init')}
    return render_template('admin/settings.html', user=session['user'], settings=settings_data)

@admin_bp.route('/reports')
@admin_required
def reports():
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_contacts = ex.submit(lambda: [d.to_dict() for d in db.collection('contact_us').order_by('timestamp', direction=firestore.Query.DESCENDING).get()])
        f_logs = ex.submit(lambda: [d.to_dict() for d in db.collection('logs').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(100).get()])
        f_users = ex.submit(lambda: [dict(d.to_dict(), id=d.id) for d in db.collection('users').get()])
        contacts = f_contacts.result()
        all_logs = f_logs.result()
        users = f_users.result()
    return render_template('admin/reports.html', user=session['user'],
        contacts=contacts, logs=all_logs, users=users)

@admin_bp.route('/monitoring')
@admin_required
def monitoring():
    return render_template('admin/monitoring.html', user=session['user'],
        mqtt_connected=mqtt_bridge.is_connected())

@admin_bp.route('/privacy')
@admin_required
def privacy():
    return render_template('admin/privacy.html', user=session['user'])

@admin_bp.route('/scenes', methods=['GET'])
@admin_required
def scenes():
    scene_docs = db.collection('scenes').get()
    all_scenes = [{**doc.to_dict(), 'id': doc.id} for doc in scene_docs]
    return render_template('admin/scenes.html', user=session['user'],
        scenes=all_scenes, devices=LEGACY_DEVICES)

@admin_bp.route('/scenes/create', methods=['POST'])
@admin_required
def create_scene():
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', 'bi-magic')
    device_keys = request.form.getlist('devices')
    device_states = request.form.getlist('states')

    if not name:
        flash('Scene name is required.', 'danger')
        return redirect(url_for('admin.scenes'))

    actions = []
    for i, dk in enumerate(device_keys):
        actions.append({
            'device': dk,
            'state': device_states[i] == 'on' if i < len(device_states) else False
        })

    db.collection('scenes').add({
        'name': name,
        'icon': icon,
        'actions': actions,
        'createdBy': session['user']['id'],
        'createdAt': datetime.now()
    })

    log_action(f'Created scene: {name}')
    flash(f'Scene "{name}" created!', 'success')
    return redirect(url_for('admin.scenes'))

@admin_bp.route('/scheduler', methods=['GET'])
@admin_required
def scheduler():
    schedule_docs = db.collection('schedules').order_by('time').get()
    schedules = [{**doc.to_dict(), 'id': doc.id} for doc in schedule_docs]
    return render_template('admin/scheduler.html', user=session['user'],
        schedules=schedules, devices=LEGACY_DEVICES)

@admin_bp.route('/scheduler/create', methods=['POST'])
@admin_required
def create_schedule():
    device = request.form.get('device', '')
    action = request.form.get('action', 'off')
    time_str = request.form.get('time', '')
    repeat = request.form.get('repeat', 'once')
    days = request.form.getlist('days')

    if not device or not time_str:
        flash('Device and time are required.', 'danger')
        return redirect(url_for('admin.scheduler'))

    db.collection('schedules').add({
        'device': device,
        'action': action,
        'time': time_str,
        'repeat': repeat,
        'days': days,
        'enabled': True,
        'createdBy': session['user']['id'],
        'createdAt': datetime.now()
    })

    log_action(f'Created schedule for {device} at {time_str}')
    flash('Schedule created!', 'success')
    return redirect(url_for('admin.scheduler'))

@admin_bp.route('/search')
@admin_required
def search():
    q = request.args.get('query', '').lower().strip()
    all_users = [dict(d.to_dict(), id=d.id) for d in db.collection('users').get()
                 if q in d.to_dict().get('username', '').lower() or q in d.to_dict().get('email', '').lower()]
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify([u['username'] for u in all_users])
    return render_template('admin/search_results.html', user=session['user'], query=q, users=all_users)


# ═══════════════════════════════════════════════════════════════════════════════
# SUPER ADMIN BLUEPRINT — Platform-wide management
# ═══════════════════════════════════════════════════════════════════════════════
super_bp = Blueprint('super', __name__, url_prefix='/super')

@super_bp.route('/platform')
@super_admin_required
def platform():
    """Global platform overview — all homes, users, devices"""
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_users = ex.submit(_fb_get_count, 'users')
        f_homes = ex.submit(_fb_get_count, 'homes')
        f_devices = ex.submit(_fb_get_count, 'devices')
        f_logs = ex.submit(_fb_get_logs_today)

        users_count = f_users.result()
        homes_count = f_homes.result()
        devices_count = f_devices.result()
        logs_today = f_logs.result()

    return render_template('super/platform.html',
        user=session['user'],
        users_count=users_count,
        homes_count=homes_count,
        devices_count=devices_count,
        logs_today=logs_today,
        mqtt_connected=mqtt_bridge.is_connected()
    )

@super_bp.route('/ota/push', methods=['POST'])
@super_admin_required
def ota_push():
    """Push OTA firmware update to a device"""
    device_id = request.form.get('device_id', '')
    firmware_url = request.form.get('firmware_url', '')
    sha256 = request.form.get('sha256', '')

    if not all([device_id, firmware_url, sha256]):
        flash('All fields required for OTA push.', 'danger')
        return redirect(url_for('super.platform'))

    ok = mqtt_bridge.publish_ota(device_id, firmware_url, sha256)
    if ok:
        log_action(f'OTA push to {device_id}')
        flash(f'OTA firmware pushed to {device_id}', 'success')
    else:
        flash('OTA push failed — MQTT not connected.', 'danger')

    return redirect(url_for('super.platform'))


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API — ESP device status endpoint
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/esp/status')
def esp_status():
    return jsonify(cache.get_all())

@app.route('/api/mqtt/status')
def mqtt_status():
    return jsonify({
        'connected': mqtt_bridge.is_connected(),
        'devices': mqtt_bridge.get_all_states()
    })

# ─── ERROR HANDLERS ──────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('errors/500.html'), 500

# ─── REGISTER BLUEPRINTS ─────────────────────────────────────────────────────
app.register_blueprint(home_bp)
app.register_blueprint(user_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(super_bp)

# ─── MQTT CALLBACKS → FIRESTORE ──────────────────────────────────────────────
def on_device_status_update(device_id, payload):
    """Called by MQTT bridge when device publishes status"""
    try:
        doc_ref = db.collection('devices').document(device_id)
        doc_ref.set({
            'status': payload.get('state', 'OFF'),
            'lastSeen': datetime.now(),
            'rssi': payload.get('rssi', 0),
            'uptime': payload.get('uptime', 0)
        }, merge=True)
    except Exception as e:
        print(f"[Firestore] Status update error for {device_id}: {e}")

def on_device_heartbeat_update(device_id, payload):
    """Called by MQTT bridge when device publishes heartbeat"""
    try:
        doc_ref = db.collection('devices').document(device_id)
        doc_ref.set({
            'lastSeen': datetime.now(),
            'rssi': payload.get('rssi', 0),
            'uptime': payload.get('uptime', 0)
        }, merge=True)
    except Exception as e:
        print(f"[Firestore] Heartbeat update error for {device_id}: {e}")

def on_device_offline(device_id):
    """Called by MQTT bridge when device goes offline"""
    try:
        doc_ref = db.collection('devices').document(device_id)
        doc_ref.set({'status': 'offline'}, merge=True)
    except Exception as e:
        print(f"[Firestore] Offline update error for {device_id}: {e}")

mqtt_bridge.on_device_status = on_device_status_update
mqtt_bridge.on_device_heartbeat = on_device_heartbeat_update
mqtt_bridge.on_device_offline = on_device_offline

# ─── INITIALIZATION ──────────────────────────────────────────────────────────
def _init_user(uid_email, password, display_name, collection, role, username):
    try:
        try:
            user = firebase_auth.get_user_by_email(uid_email)
        except firebase_auth.UserNotFoundError:
            try:
                user = firebase_auth.create_user(
                    email=uid_email,
                    password=password,
                    display_name=display_name
                )
                print(f"[Init] Firebase Auth user created for {uid_email}")
            except Exception as e:
                print(f"[Init] Failed to create Firebase Auth user {uid_email} - {e}")
                return
                
        # Now check Firestore
        doc_ref = db.collection(collection).document(user.uid)
        doc = doc_ref.get()
        if not doc.exists:
            doc_ref.set({
                'full_name': display_name,
                'username': username,
                'email': uid_email,
                'role': role,
                'suspended': False,
                'created_at': datetime.now()
            })
            print(f"[Init] Firestore profile created for {uid_email}")
    except Exception as e:
        print(f"[Init Warning] Skipping user creation for {uid_email} because Firebase Auth is not configured properly.")
        print(f"               Error: {e}")

def init_db():
    """Create default admin accounts and collections synced with Firebase Auth"""
    _init_user('admin@brighthaven.com', 'admin@123', 'Maulin K Patel', 'super_admin', 'super_admin', 'maulin18203')
    _init_user('mkp@brighthaven.com', '9909618203', 'MKP Admin', 'admin', 'admin', 'mkp18203')
    _init_user('mkp6952@brighthaven.com', '9909618203', 'MKP Super Admin', 'super_admin', 'super_admin', 'mkp6952')
    _init_user('maulin@example.com', 'user@123', 'Maulin K Patel', 'users', 'user', 'maulin6952')

    # Ensure collections exist
    for col in ['logs', 'contact_us', 'notifications', 'settings', 'homes', 'rooms', 'devices', 'permissions', 'scenes', 'schedules']:
        if not db.collection(col).limit(1).get():
            db.collection(col).add({'_init': True, 'timestamp': datetime.now()})

    # Default home
    homes = db.collection('homes').where(filter=FieldFilter('name', '==', 'BrightHaven Home')).limit(1).get()
    if not homes:
        db.collection('homes').add({
            'name': 'BrightHaven Home',
            'ownerId': 'default',
            'timezone': 'Asia/Kolkata',
            'memberCount': 1,
            'createdAt': datetime.now()
        })
        print("[Init] Default home created")

print("\n╔══════════════════════════════════════════════════════════════╗")
print("║          BrightHaven Cloud IoT Platform v2.0               ║")
print("╚══════════════════════════════════════════════════════════════╝\n")

print("[System] Initializing database...")
init_db()

if GPIO_AVAILABLE:
    print("[GPIO] Initializing Raspberry Pi GPIO pins...")
    gpio_ctrl.init_pins()

print("[MQTT] Connecting to broker...")
mqtt_bridge.connect()
mqtt_bridge.start_watchdog()

if BLYNK_TOKEN_ESP8266 or BLYNK_TOKEN_ESP32:
    print(f"[Blynk] ESP8266 token: {'✅' if BLYNK_TOKEN_ESP8266 else '❌'}")
    print(f"[Blynk] ESP32 token:   {'✅' if BLYNK_TOKEN_ESP32 else '❌'}")
    print("[Blynk] Fetching initial device states...")
    cache.refresh_all()
    cache.start_background_refresh()
else:
    print("[Blynk] No tokens configured — legacy Blynk disabled")

print("[Server] BrightHaven Cloud IoT Platform Ready ✅\n")

if __name__ == '__main__':
    import socket

    # Use FLASK_PORT from run.sh if available, otherwise find a free one
    env_port = os.getenv('FLASK_PORT')
    if env_port:
        port = int(env_port)
    else:
        def find_free_port(start=5000, max_tries=20):
            for p in range(start, start + max_tries):
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.bind(('', p))
                        return p
                except OSError:
                    continue
            return start + max_tries
        port = find_free_port()

    print(f"[Server] Starting on port {port}")
    try:
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    finally:
        mqtt_bridge.disconnect()
        if GPIO_AVAILABLE:
            print("[GPIO] Cleaning up pins...")
            GPIO.cleanup()
