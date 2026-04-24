# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import base64
import re

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback-secret-change-me")

# === YOUR FIREBASE CONFIG ===
FIREBASE_CONFIG = {
    "apiKey": "AIzaSyBXn_X7c-Pevqrnpwd-I43-DbRGVOeBiEg",
    "authDomain": "squash79-store.firebaseapp.com",
    "databaseURL": "https://squash79-store-default-rtdb.firebaseio.com",
    "projectId": "squash79-store",
    "storageBucket": "squash79-store.firebasestorage.app",
    "messagingSenderId": "963643117351",
    "appId": "1:963643117351:web:17be7e72b5fbf3c0646302"
}
API_KEY = FIREBASE_CONFIG["apiKey"]
DATABASE_URL = FIREBASE_CONFIG["databaseURL"]

# ---------- Helper Functions ----------
def _make_request(url, method="GET", data=None, headers=None):
    if headers is None:
        headers = {}
    if data is not None:
        data = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return json.loads(body)
        except:
            return {"error": {"message": body}}

def sign_in(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}"
    return _make_request(url, "POST", {"email": email, "password": password, "returnSecureToken": True})

def sign_up(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={API_KEY}"
    return _make_request(url, "POST", {"email": email, "password": password, "returnSecureToken": True})

def update_email(id_token, new_email):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={API_KEY}"
    return _make_request(url, "POST", {"idToken": id_token, "email": new_email, "returnSecureToken": True})

def send_verification_email(id_token):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={API_KEY}"
    return _make_request(url, "POST", {"requestType": "VERIFY_EMAIL", "idToken": id_token})

def get_account_info(id_token):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={API_KEY}"
    return _make_request(url, "POST", {"idToken": id_token})

def db_put(path, data, token):
    return _make_request(f"{DATABASE_URL}{path}.json?auth={token}", "PUT", data)

def db_patch(path, data, token):
    return _make_request(f"{DATABASE_URL}{path}.json?auth={token}", "PATCH", data)

def db_post(path, data, token):
    return _make_request(f"{DATABASE_URL}{path}.json?auth={token}", "POST", data)

def db_get(path, token):
    return _make_request(f"{DATABASE_URL}{path}.json?auth={token}", "GET")

def db_delete(path, token):
    return _make_request(f"{DATABASE_URL}{path}.json?auth={token}", "DELETE")

def get_uid_from_token(id_token):
    try:
        payload = id_token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload).decode('utf-8')
        return json.loads(decoded).get('user_id')
    except:
        return None

def get_chat_id(uid1, uid2):
    return "_".join(sorted([uid1, uid2]))

def add_notification(to_uid, from_uid, notif_type, token, extra=None):
    notif = {
        "type": notif_type,
        "from_uid": from_uid,
        "timestamp": int(time.time() * 1000),
        "seen": False
    }
    if extra:
        notif.update(extra)
    sender = db_get(f"/users/{from_uid}", token)
    if isinstance(sender, dict):
        notif["sender_name"] = sender.get("username", from_uid)
    else:
        notif["sender_name"] = from_uid
    db_post(f"/notifications/{to_uid}", notif, token)

def is_online(user_data):
    """Return True if last_online is within the last 45 seconds."""
    if not isinstance(user_data, dict):
        return False
    last = user_data.get("last_online", 0)
    now = int(time.time() * 1000)
    return (now - last) < 45000  # 45 seconds

# ==================== ROUTES ====================
# (Login, signup, etc. unchanged, except we add last_online to profile creation)

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        result = sign_in(email, password)
        if "idToken" in result:
            id_token = result["idToken"]
            info = get_account_info(id_token)
            email_verified = False
            if "users" in info and info["users"]:
                email_verified = info["users"][0].get("emailVerified", False)
            session["user"] = email
            session["id_token"] = id_token
            uid = get_uid_from_token(id_token)
            session["uid"] = uid
            profile = db_get(f"/users/{uid}", id_token)
            if isinstance(profile, dict):
                session["username"] = profile.get("username", email)
                session["isAdmin"] = profile.get("isAdmin", False)
                session["verified"] = profile.get("verified", False)
                session["dark_mode"] = profile.get("dark_mode", False)
                if profile.get("banned", False):
                    session.clear()
                    return "Your account has been banned."
            else:
                session["username"] = email
                session["isAdmin"] = False
                session["verified"] = False
                session["dark_mode"] = False
            session["email_verified"] = email_verified
            # Update last_online on login
            db_patch(f"/users/{uid}", {"last_online": int(time.time() * 1000)}, id_token)
            return redirect(url_for("feed"))
        else:
            error = result.get("error", {}).get("message", "Login failed")
            return f"Login failed: {error}"
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        username = request.form.get("username", "").strip()
        if len(password) < 8:
            return "Password must be at least 8 characters."
        if not re.search(r"[A-Z]", password):
            return "Password must contain an uppercase letter."
        if not re.search(r"[a-z]", password):
            return "Password must contain a lowercase letter."
        if not re.search(r"[0-9]", password):
            return "Password must contain a digit."
        result = sign_up(email, password)
        if "idToken" in result:
            id_token = result["idToken"]
            uid = get_uid_from_token(id_token)
            all_users = db_get("/users", id_token)
            first_user = (not all_users or len(all_users) == 0)
            profile = {
                "email": email,
                "username": username or email.split('@')[0],
                "bio": "",
                "profile_pic": "",
                "verified": False,
                "banned": False,
                "isAdmin": first_user,
                "dark_mode": False,
                "last_online": 0  # initially offline
            }
            db_put(f"/users/{uid}", profile, id_token)
            send_verification_email(id_token)
            return redirect(url_for("login"))
        else:
            error = result.get("error", {}).get("message", "Signup failed")
            return f"Signup failed: {error}"
    return render_template("signup.html")

# ... (keep all other routes exactly as before) ...

# ======= NEW: Online status ping =======
@app.route("/api/ping", methods=["POST"])
def api_ping():
    if "user" not in session:
        return jsonify({"success": False}), 401
    db_patch(f"/users/{session['uid']}", {"last_online": int(time.time() * 1000)}, session["id_token"])
    return jsonify({"success": True})

# ... (rest of the app) ...
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
