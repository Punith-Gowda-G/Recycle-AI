import os
import json
import math
import sqlite3
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from flask_wtf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "instance" / "recyclelink.db"))
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
MATERIALS = ["Plastic", "Paper", "Cardboard", "Metal", "E-waste", "Glass", "Textiles", "Other"]
LISTING_STATUSES = {"available", "reserved", "collected"}
PICKUP_STATUSES = {"pending", "accepted", "rejected", "completed"}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-this-secret-key"),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    UPLOAD_FOLDER=str(UPLOAD_FOLDER),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
CSRFProtect(app)
DATABASE.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('member', 'admin')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS waste_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            material TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL CHECK(quantity > 0),
            unit TEXT NOT NULL DEFAULT 'kg' CHECK(unit IN ('kg', 'items', 'bags')),
            price_per_unit REAL NOT NULL DEFAULT 0 CHECK(price_per_unit >= 0),
            location TEXT NOT NULL,
            image_filename TEXT,
            status TEXT NOT NULL DEFAULT 'available' CHECK(status IN ('available', 'reserved', 'collected')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pickup_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL REFERENCES waste_listings(id) ON DELETE CASCADE,
            recycler_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            pickup_date TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected', 'completed')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(listing_id, recycler_id)
        );
        CREATE INDEX IF NOT EXISTS idx_listings_status ON waste_listings(status);
        CREATE INDEX IF NOT EXISTS idx_listings_material ON waste_listings(material);
        CREATE INDEX IF NOT EXISTS idx_pickups_recycler ON pickup_requests(recycler_id);
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            link TEXT NOT NULL DEFAULT '/dashboard',
            is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read, id DESC);
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pickup_id INTEGER NOT NULL REFERENCES pickup_requests(id) ON DELETE CASCADE,
            reviewer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reviewee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pickup_id, reviewer_id)
        );
        CREATE TABLE IF NOT EXISTS ai_detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            filename TEXT,
            predicted_label TEXT NOT NULL,
            confidence REAL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Safe, additive migrations for databases created by earlier RecycleLink versions.
    columns = {row[1] for row in db.execute("PRAGMA table_info(waste_listings)").fetchall()}
    if "latitude" not in columns:
        db.execute("ALTER TABLE waste_listings ADD COLUMN latitude REAL")
    if "longitude" not in columns:
        db.execute("ALTER TABLE waste_listings ADD COLUMN longitude REAL")
    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    if admin_email:
        db.execute("UPDATE users SET role = 'admin' WHERE lower(email) = ?", (admin_email,))
    db.commit()
    db.close()


init_db()


def current_user():
    if "user_id" not in session:
        return None
    if "user" not in g:
        g.user = get_db().execute("SELECT id, name, email, role FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return g.user


@app.before_request
def load_user():
    g.user = None
    if session.get("user_id"):
        g.user = get_db().execute(
            "SELECT id, name, email, role FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if g.user is None:
            session.clear()


@app.context_processor
def inject_globals():
    user = current_user()
    unread = 0
    if user:
        unread = get_db().execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0", (user["id"],)).fetchone()[0]
    return {"current_user": user, "today": date.today().isoformat(), "unread_notifications": unread}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please log in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_image(file):
    if not file or not file.filename:
        return None
    if not allowed_file(file.filename):
        raise ValueError("Image must be PNG, JPG, JPEG, WEBP, or GIF.")
    safe_name = secure_filename(file.filename)
    stem, ext = os.path.splitext(safe_name)
    filename = f"{stem[:60]}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}{ext.lower()}"
    file.save(UPLOAD_FOLDER / filename)
    return filename


@app.route("/")
def index():
    db = get_db()
    stats = {
        "listings": db.execute("SELECT COUNT(*) FROM waste_listings WHERE status = 'available'").fetchone()[0],
        "materials": db.execute("SELECT COUNT(DISTINCT material) FROM waste_listings WHERE status = 'available'").fetchone()[0],
        "collections": db.execute("SELECT COUNT(*) FROM pickup_requests WHERE status = 'completed'").fetchone()[0],
    }
    listings = db.execute("""SELECT l.*, u.name AS seller_name FROM waste_listings l
        JOIN users u ON u.id = l.seller_id WHERE l.status = 'available'
        ORDER BY l.created_at DESC LIMIT 6""").fetchall()
    return render_template("index.html", stats=stats, listings=listings)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if len(name) < 2:
            flash("Enter your full name (at least 2 characters).", "error")
        elif "@" not in email or "." not in email.split("@")[-1]:
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
        else:
            try:
                db = get_db()
                role = "admin" if email == os.environ.get("ADMIN_EMAIL", "").strip().lower() and email else "member"
                cursor = db.execute("INSERT INTO users(name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                                    (name, email, generate_password_hash(password), role))
                db.commit()
                session.clear()
                session["user_id"] = cursor.lastrowid
                flash("Welcome to RecycleLink! Your account is ready.", "success")
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash("An account with that email already exists.", "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['name'].split()[0]}.", "success")
            next_url = request.args.get("next", "")
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/marketplace")
def marketplace():
    db = get_db()
    search = request.args.get("q", "").strip()[:100]
    material = request.args.get("material", "").strip()
    sort = request.args.get("sort", "newest")
    query = """SELECT l.*, u.name AS seller_name FROM waste_listings l
               JOIN users u ON u.id = l.seller_id WHERE l.status = 'available'"""
    params = []
    if search:
        query += " AND (l.title LIKE ? OR l.description LIKE ? OR l.location LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    if material in MATERIALS:
        query += " AND l.material = ?"
        params.append(material)
    ordering = {"newest": "l.created_at DESC", "price_low": "l.price_per_unit ASC", "price_high": "l.price_per_unit DESC", "quantity": "l.quantity DESC"}.get(sort, "l.created_at DESC")
    listings = db.execute(query + " ORDER BY " + ordering, params).fetchall()
    return render_template("marketplace.html", listings=listings, materials=MATERIALS, search=search, material=material, sort=sort)


@app.route("/listings/new", methods=["GET", "POST"])
@login_required
def create_listing():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        material = request.form.get("material", "")
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        unit = request.form.get("unit", "kg")
        try:
            quantity = float(request.form.get("quantity", "0"))
            price = float(request.form.get("price_per_unit", "0"))
        except ValueError:
            quantity, price = 0, -1
        if not title or len(title) > 100:
            flash("Title is required and must be under 100 characters.", "error")
        elif material not in MATERIALS:
            flash("Choose a valid material category.", "error")
        elif not location or len(location) > 120:
            flash("Enter a pickup location (under 120 characters).", "error")
        elif quantity <= 0 or quantity > 1_000_000 or price < 0 or price > 1_000_000:
            flash("Enter a positive quantity and a non-negative price.", "error")
        elif unit not in {"kg", "items", "bags"}:
            flash("Choose a valid unit.", "error")
        else:
            try:
                image_filename = save_uploaded_image(request.files.get("image"))
                db = get_db()
                db.execute("""INSERT INTO waste_listings
                    (seller_id, title, material, description, quantity, unit, price_per_unit, location, image_filename)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (current_user()["id"], title, material, description, quantity, unit, price, location, image_filename))
                db.commit()
                flash("Your waste listing is now live.", "success")
                return redirect(url_for("marketplace"))
            except ValueError as error:
                flash(str(error), "error")
    return render_template("create_listing.html", materials=MATERIALS)


@app.route("/listings/<int:listing_id>")
def listing_detail(listing_id):
    listing = get_db().execute("""SELECT l.*, u.name AS seller_name FROM waste_listings l
        JOIN users u ON u.id = l.seller_id WHERE l.id = ?""", (listing_id,)).fetchone()
    if listing is None:
        abort(404)
    existing_request = None
    if current_user():
        existing_request = get_db().execute("SELECT id, status FROM pickup_requests WHERE listing_id = ? AND recycler_id = ?",
                                            (listing_id, current_user()["id"])).fetchone()
    return render_template("listing_detail.html", listing=listing, existing_request=existing_request)


@app.route("/listings/<int:listing_id>/request-pickup", methods=["POST"])
@login_required
def request_pickup(listing_id):
    db = get_db()
    listing = db.execute("SELECT * FROM waste_listings WHERE id = ?", (listing_id,)).fetchone()
    if listing is None:
        abort(404)
    if listing["seller_id"] == current_user()["id"]:
        flash("You cannot request a pickup for your own listing.", "error")
        return redirect(url_for("listing_detail", listing_id=listing_id))
    if listing["status"] != "available":
        flash("This listing is no longer available.", "error")
        return redirect(url_for("listing_detail", listing_id=listing_id))
    pickup_date = request.form.get("pickup_date", "")
    message = request.form.get("message", "").strip()[:500]
    try:
        parsed_date = date.fromisoformat(pickup_date)
        if parsed_date < date.today():
            raise ValueError
    except ValueError:
        flash("Choose a valid pickup date that is today or later.", "error")
        return redirect(url_for("listing_detail", listing_id=listing_id))
    try:
        db.execute("INSERT INTO pickup_requests(listing_id, recycler_id, pickup_date, message) VALUES (?, ?, ?, ?)",
                   (listing_id, current_user()["id"], pickup_date, message))
        db.commit()
        notify_user(db, listing["seller_id"], "New pickup request", f"Someone requested {listing['title']}.", url_for("dashboard"))
        db.commit()
        flash("Pickup request sent to the seller.", "success")
    except sqlite3.IntegrityError:
        flash("You have already requested this listing.", "info")
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    uid = current_user()["id"]
    listings = db.execute("SELECT * FROM waste_listings WHERE seller_id = ? ORDER BY created_at DESC", (uid,)).fetchall()
    incoming = db.execute("""SELECT p.*, l.title AS listing_title, l.seller_id, l.material, l.quantity, l.unit,
        u.name AS recycler_name, u.email AS recycler_email FROM pickup_requests p
        JOIN waste_listings l ON l.id = p.listing_id JOIN users u ON u.id = p.recycler_id
        WHERE l.seller_id = ? ORDER BY p.created_at DESC""", (uid,)).fetchall()
    outgoing = db.execute("""SELECT p.*, l.title AS listing_title, l.material, l.quantity, l.unit,
        l.location, u.name AS seller_name FROM pickup_requests p
        JOIN waste_listings l ON l.id = p.listing_id JOIN users u ON u.id = l.seller_id
        WHERE p.recycler_id = ? ORDER BY p.created_at DESC""", (uid,)).fetchall()
    stats = {
        "my_listings": len(listings),
        "available": sum(1 for x in listings if x["status"] == "available"),
        "incoming_pending": sum(1 for x in incoming if x["status"] == "pending"),
        "my_completed": sum(1 for x in outgoing if x["status"] == "completed"),
        "waste_listed": round(sum(x["quantity"] for x in listings), 2),
    }
    monthly = db.execute("""SELECT substr(created_at, 1, 7) AS month, COUNT(*) AS count
        FROM waste_listings WHERE seller_id = ? GROUP BY month ORDER BY month DESC LIMIT 6""", (uid,)).fetchall()
    monthly = list(reversed(monthly))
    return render_template("dashboard.html", listings=listings, incoming=incoming, outgoing=outgoing, stats=stats, monthly=monthly)


@app.route("/pickups/<int:pickup_id>/update", methods=["POST"])
@login_required
def update_pickup(pickup_id):
    new_status = request.form.get("status", "")
    if new_status not in PICKUP_STATUSES - {"pending"}:
        flash("Invalid pickup status.", "error")
        return redirect(url_for("dashboard"))
    db = get_db()
    pickup = db.execute("""SELECT p.*, l.seller_id, l.id AS listing_id, l.status AS listing_status FROM pickup_requests p
        JOIN waste_listings l ON l.id = p.listing_id WHERE p.id = ?""", (pickup_id,)).fetchone()
    if pickup is None:
        abort(404)
    uid = current_user()["id"]
    if pickup["seller_id"] != uid and pickup["recycler_id"] != uid:
        abort(403)
    if new_status == "accepted" or new_status == "rejected":
        if pickup["seller_id"] != uid:
            abort(403)
        if pickup["status"] != "pending":
            flash("Only pending requests can be accepted or rejected.", "error")
            return redirect(url_for("dashboard"))
        if new_status == "accepted" and pickup["listing_status"] != "available":
            flash("This listing has already been reserved or collected. This request cannot be accepted.", "error")
            return redirect(url_for("dashboard"))
        db.execute("UPDATE pickup_requests SET status = ? WHERE id = ?", (new_status, pickup_id))
        if new_status == "accepted":
            db.execute("UPDATE waste_listings SET status = 'reserved' WHERE id = ? AND status = 'available'", (pickup["listing_id"],))
            db.execute("UPDATE pickup_requests SET status = 'rejected' WHERE listing_id = ? AND id != ? AND status = 'pending'", (pickup["listing_id"], pickup_id))
    elif new_status == "completed":
        if pickup["status"] != "accepted":
            flash("Only accepted pickups can be marked completed.", "error")
            return redirect(url_for("dashboard"))
        # Either party can confirm completion; a real deployment could require both parties.
        db.execute("UPDATE pickup_requests SET status = 'completed' WHERE id = ?", (pickup_id,))
        db.execute("UPDATE waste_listings SET status = 'collected' WHERE id = ?", (pickup["listing_id"],))
    db.commit()
    recipient_id = pickup["recycler_id"] if uid == pickup["seller_id"] else pickup["seller_id"]
    notify_user(db, recipient_id, "Pickup status updated", f"Pickup #{pickup_id} is now {new_status}.", url_for("dashboard"))
    db.commit()
    flash("Pickup request updated.", "success")
    return redirect(url_for("dashboard"))


@app.route("/listings/<int:listing_id>/delete", methods=["POST"])
@login_required
def delete_listing(listing_id):
    db = get_db()
    listing = db.execute("SELECT * FROM waste_listings WHERE id = ?", (listing_id,)).fetchone()
    if listing is None:
        abort(404)
    if listing["seller_id"] != current_user()["id"]:
        abort(403)
    if db.execute("SELECT COUNT(*) FROM pickup_requests WHERE listing_id = ? AND status IN ('accepted', 'completed')", (listing_id,)).fetchone()[0]:
        flash("A listing with an accepted or completed pickup cannot be deleted.", "error")
    else:
        db.execute("DELETE FROM waste_listings WHERE id = ?", (listing_id,))
        db.commit()
        if listing["image_filename"]:
            try:
                (UPLOAD_FOLDER / listing["image_filename"]).unlink(missing_ok=True)
            except OSError:
                pass
        flash("Listing deleted.", "success")
    return redirect(url_for("dashboard"))



# ---------- RecycleLink feature extensions ----------
def notify_user(db, user_id, title, body, link="/dashboard"):
    """Store an in-app notification; clients poll the unread endpoint for updates."""
    if user_id:
        db.execute("INSERT INTO notifications(user_id, title, body, link) VALUES (?, ?, ?, ?)",
                   (user_id, title[:100], body[:300], link[:250]))


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user()["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@app.route("/features")
def features_hub():
    return render_template("features.html", materials=MATERIALS)


@app.route("/recommendations")
@login_required
def recommendations():
    db = get_db()
    listing_id = request.args.get("listing_id", type=int)
    if listing_id:
        listing = db.execute("SELECT * FROM waste_listings WHERE id = ?", (listing_id,)).fetchone()
        if listing is None:
            abort(404)
        if listing["seller_id"] != current_user()["id"]:
            abort(403)
        # Recommend recycler accounts that previously requested similar materials.
        history = db.execute("""SELECT u.id, u.name, u.email,
                COUNT(p.id) AS previous_requests,
                SUM(CASE WHEN p.status = 'completed' THEN 1 ELSE 0 END) AS completed_pickups,
                SUM(CASE WHEN l.material = ? THEN 1 ELSE 0 END) AS same_material_requests,
                GROUP_CONCAT(l.location, ' ') AS past_locations
            FROM users u JOIN pickup_requests p ON p.recycler_id = u.id
            JOIN waste_listings l ON l.id = p.listing_id
            WHERE u.id != ? GROUP BY u.id""", (listing["material"], current_user()["id"])).fetchall()
        target_terms = {x.lower() for x in listing["location"].replace(",", " ").split() if len(x) > 2}
        matches = []
        for recycler in history:
            past_terms = {x.lower() for x in (recycler["past_locations"] or "").replace(",", " ").split() if len(x) > 2}
            overlap = len(target_terms & past_terms)
            score = min(int(recycler["same_material_requests"] or 0) * 25, 50) + min(int(recycler["completed_pickups"] or 0) * 5, 25) + min(overlap * 10, 25)
            matches.append({"recycler": recycler, "score": score, "location_overlap": overlap})
        matches.sort(key=lambda x: (-x["score"], -int(x["recycler"]["completed_pickups"] or 0)))
        return render_template("features.html", tool="matching_recyclers", target_listing=listing, recycler_matches=matches[:20])

    material = request.args.get("material", "")
    location = request.args.get("location", "").strip()[:120]
    if material not in MATERIALS:
        material = ""
    # Recommend available listings by material + shared location words + seller history.
    query = """SELECT l.*, u.name AS seller_name,
        (SELECT COUNT(*) FROM pickup_requests p WHERE p.recycler_id = u.id AND p.status = 'completed') AS completed_pickups
        FROM waste_listings l JOIN users u ON u.id = l.seller_id WHERE l.status = 'available' AND l.seller_id != ?"""
    params = [current_user()["id"]]
    if material:
        query += " AND l.material = ?"
        params.append(material)
    listings = db.execute(query, params).fetchall()
    loc_terms = {x.lower() for x in location.replace(",", " ").split() if len(x) > 2}
    ranked = []
    for item in listings:
        listing_terms = {x.lower() for x in item["location"].replace(",", " ").split() if len(x) > 2}
        overlap = len(loc_terms & listing_terms)
        score = (35 if material and item["material"] == material else 0) + min(overlap * 15, 45) + min(item["completed_pickups"] * 4, 20)
        ranked.append({"listing": item, "score": score, "shared_location_terms": overlap})
    ranked.sort(key=lambda x: (-x["score"], x["listing"]["price_per_unit"]))
    return render_template("features.html", materials=MATERIALS, recommendations=ranked[:12], selected_material=material, selected_location=location, tool="matching")

# Conversion factors are illustrative demo assumptions (kg CO2e per kg of material).
# Replace them with region-specific, documented lifecycle factors before making public claims.
IMPACT_FACTORS = {"Plastic": 1.5, "Paper": 1.0, "Cardboard": 0.9, "Metal": 4.0,
                  "E-waste": 2.0, "Glass": 0.3, "Textiles": 3.0, "Other": 0.5}


@app.route("/impact")
@login_required
def impact_dashboard():
    db = get_db()
    rows = db.execute("""SELECT l.material, SUM(l.quantity) AS quantity, l.unit
        FROM pickup_requests p JOIN waste_listings l ON l.id = p.listing_id
        WHERE p.status = 'completed' AND l.unit = 'kg' AND (l.seller_id = ? OR p.recycler_id = ?)
        GROUP BY l.material, l.unit""", (current_user()["id"], current_user()["id"])).fetchall()
    by_material = []
    total_kg = 0.0
    estimated_co2 = 0.0
    for row in rows:
        quantity = float(row["quantity"] or 0)
        factor = IMPACT_FACTORS.get(row["material"], 0.0)
        total_kg += quantity
        estimated_co2 += quantity * factor
        by_material.append({"material": row["material"], "quantity": round(quantity, 2), "co2": round(quantity * factor, 2)})
    return render_template("features.html", tool="impact", impact={"total_kg": round(total_kg, 2), "estimated_co2": round(estimated_co2, 2), "by_material": by_material})


@app.route("/tools/route-planner", methods=["GET", "POST"])
@login_required
def route_planner():
    route = []
    total_distance = 0.0
    error = None
    raw = request.form.get("stops", "") if request.method == "POST" else ""
    if request.method == "POST":
        points = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 3:
                error = "Enter each stop as Name, latitude, longitude (one per line)."
                break
            try:
                lat, lon = float(parts[1]), float(parts[2])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError
                points.append({"name": parts[0][:80], "lat": lat, "lon": lon})
            except ValueError:
                error = "Latitude/longitude must be valid numbers in the accepted ranges."
                break
        if not error and len(points) < 2:
            error = "Enter at least two stops to optimize a route."
        if not error and len(points) > 25:
            error = "For this demo, optimize at most 25 stops at a time."
        if not error:
            # Nearest-neighbour heuristic using straight-line Haversine distance.
            remaining = points[:]
            route = [remaining.pop(0)]
            while remaining:
                last = route[-1]
                def km(point):
                    r = 6371.0
                    p1, p2 = math.radians(last["lat"]), math.radians(point["lat"])
                    dp = math.radians(point["lat"] - last["lat"])
                    dl = math.radians(point["lon"] - last["lon"])
                    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
                    return 2*r*math.asin(min(1, math.sqrt(a)))
                nxt = min(remaining, key=km)
                total_distance += km(nxt)
                route.append(nxt)
                remaining.remove(nxt)
            total_distance = round(total_distance, 2)
    return render_template("features.html", tool="route", route=route, total_distance=total_distance, route_error=error, stops_input=raw)


@app.route("/tools/ai-detect", methods=["GET", "POST"])
@login_required
def ai_detect():
    result = None
    error = None
    if request.method == "POST":
        image_file = request.files.get("image")
        if not image_file or not image_file.filename or not allowed_file(image_file.filename):
            error = "Upload a PNG, JPG, JPEG, WEBP, or GIF image."
        elif Path(os.environ.get("LOCAL_MODEL_PATH", BASE_DIR / "models" / "waste_classifier.joblib")).exists():
            try:
                from local_classifier import predict

                label, confidence = predict(
                    image_file.read(),
                    Path(os.environ.get("LOCAL_MODEL_PATH", BASE_DIR / "models" / "waste_classifier.joblib")),
                )
                db = get_db()
                db.execute(
                    "INSERT INTO ai_detections(user_id, predicted_label, confidence) VALUES (?, ?, ?)",
                    (current_user()["id"], label, confidence),
                )
                db.commit()
                result = {"label": label, "confidence": round(confidence * 100, 1)}
            except Exception as exc:
                error = str(exc)[:300]
        elif not os.environ.get("HF_API_TOKEN"):
            error = "AI classification needs HF_API_TOKEN and a waste-classification model configured in HF_IMAGE_MODEL. Set these environment variables, then try again."
        else:
            try:
                import requests
                model = os.environ.get("HF_IMAGE_MODEL", "").strip()
                if not model:
                    raise ValueError("Set HF_IMAGE_MODEL to a compatible image-classification model fine-tuned for waste categories.")
                image_bytes = image_file.read()
                response = requests.post(
                    f"https://router.huggingface.co/hf-inference/models/{model}",
                    headers={"Authorization": f"Bearer {os.environ['HF_API_TOKEN']}", "Content-Type": image_file.mimetype or "application/octet-stream"},
                    data=image_bytes, timeout=35)
                if response.status_code >= 400:
                    try:
                        api_error = str(response.json().get("error", "")).strip()
                    except (ValueError, AttributeError):
                        api_error = ""
                    detail = f" {api_error[:220]}" if api_error else ""
                    raise ValueError(f"Model API returned HTTP {response.status_code}.{detail}")
                predictions = response.json()
                if not isinstance(predictions, list) or not predictions:
                    raise ValueError("The model did not return classification results.")
                top = max(predictions, key=lambda x: float(x.get("score", 0)))
                label = str(top.get("label", "Unknown"))[:120]
                confidence = max(0.0, min(1.0, float(top.get("score", 0))))
                db = get_db()
                db.execute("INSERT INTO ai_detections(user_id, predicted_label, confidence) VALUES (?, ?, ?)", (current_user()["id"], label, confidence))
                db.commit()
                result = {"label": label, "confidence": round(confidence * 100, 1)}
            except Exception as exc:
                error = str(exc)[:300]
    return render_template("features.html", tool="detect", detection=result, feature_error=error)


@app.route("/tools/price-prediction", methods=["GET", "POST"])
@login_required
def price_prediction():
    prediction = None
    error = None
    material = request.form.get("material", "Cardboard")
    quantity = request.form.get("quantity", "10")
    if request.method == "POST":
        try:
            qty = float(quantity)
            if material not in MATERIALS or qty <= 0 or qty > 1_000_000:
                raise ValueError
            db = get_db()
            # Use historical listing prices for this material; median is robust to outliers.
            prices = [float(r[0]) for r in db.execute("SELECT price_per_unit FROM waste_listings WHERE material = ? AND price_per_unit > 0 ORDER BY created_at DESC LIMIT 500", (material,)).fetchall()]
            if not prices:
                error = "Not enough marketplace price data for this material yet. Add a few realistic listings first."
            else:
                prices.sort()
                median = prices[len(prices)//2] if len(prices) % 2 else (prices[len(prices)//2-1] + prices[len(prices)//2]) / 2
                # Optional lightweight regression model learns from available listing examples.
                method = "historical median baseline"
                if len(prices) >= 8:
                    try:
                        from sklearn.linear_model import LinearRegression
                        # quantity is the only continuous input in this starter dataset;
                        # predictions are clamped to observed price range to avoid wild estimates.
                        data = db.execute("SELECT quantity, price_per_unit FROM waste_listings WHERE material = ? AND price_per_unit > 0 ORDER BY created_at DESC LIMIT 500", (material,)).fetchall()
                        model = LinearRegression().fit([[float(r[0])] for r in data], [float(r[1]) for r in data])
                        value = float(model.predict([[qty]])[0])
                        method = "linear regression on existing listings"
                    except Exception:
                        value = median
                else:
                    value = median
                lo, hi = min(prices), max(prices)
                value = max(lo, min(hi, value))
                prediction = {"unit_price": round(value, 2), "total": round(value * qty, 2), "method": method, "samples": len(prices), "quantity": qty}
        except (ValueError, TypeError):
            error = "Choose a valid material and enter a positive quantity."
    return render_template("features.html", tool="price", materials=MATERIALS, prediction=prediction, feature_error=error, selected_material=material, quantity=quantity)


@app.route("/pickups/<int:pickup_id>/review", methods=["GET", "POST"])
@login_required
def review_pickup(pickup_id):
    db = get_db()
    pickup = db.execute("""SELECT p.*, l.title, l.seller_id, seller.name AS seller_name, recycler.name AS recycler_name
        FROM pickup_requests p JOIN waste_listings l ON l.id = p.listing_id
        JOIN users seller ON seller.id = l.seller_id JOIN users recycler ON recycler.id = p.recycler_id WHERE p.id = ?""", (pickup_id,)).fetchone()
    if pickup is None:
        abort(404)
    uid = current_user()["id"]
    if uid not in (pickup["seller_id"], pickup["recycler_id"]):
        abort(403)
    if pickup["status"] != "completed":
        flash("Reviews are available after a pickup is completed.", "error")
        return redirect(url_for("dashboard"))
    if db.execute("SELECT id FROM reviews WHERE pickup_id = ? AND reviewer_id = ?", (pickup_id, uid)).fetchone():
        flash("You have already reviewed this pickup.", "info")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        try:
            rating = int(request.form.get("rating", "0"))
        except ValueError:
            rating = 0
        comment = request.form.get("comment", "").strip()[:1000]
        if rating not in range(1, 6):
            flash("Choose a rating from 1 to 5 stars.", "error")
        else:
            reviewee = pickup["seller_id"] if uid == pickup["recycler_id"] else pickup["recycler_id"]
            db.execute("INSERT INTO reviews(pickup_id, reviewer_id, reviewee_id, rating, comment) VALUES (?, ?, ?, ?, ?)", (pickup_id, uid, reviewee, rating, comment))
            db.commit()
            notify_user(db, reviewee, "New marketplace review", f"You received a {rating}-star review for {pickup['title']}.", url_for("dashboard"))
            db.commit()
            flash("Thanks for sharing your review.", "success")
            return redirect(url_for("dashboard"))
    reviewee_name = pickup["seller_name"] if uid == pickup["recycler_id"] else pickup["recycler_name"]
    return render_template("features.html", tool="review", pickup=pickup, reviewee_name=reviewee_name)


@app.route("/notifications")
@login_required
def notifications_page():
    db = get_db()
    rows = db.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 100", (current_user()["id"],)).fetchall()
    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (current_user()["id"],))
    db.commit()
    return render_template("features.html", tool="notifications", notifications=rows)


@app.route("/api/notifications")
@login_required
def notifications_api():
    rows = get_db().execute("SELECT id, title, body, link, created_at FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY id DESC LIMIT 10", (current_user()["id"],)).fetchall()
    return jsonify({"unread": len(rows), "notifications": [dict(row) for row in rows]})


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        "users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "listings": db.execute("SELECT COUNT(*) FROM waste_listings").fetchone()[0],
        "pending_pickups": db.execute("SELECT COUNT(*) FROM pickup_requests WHERE status = 'pending'").fetchone()[0],
        "completed_pickups": db.execute("SELECT COUNT(*) FROM pickup_requests WHERE status = 'completed'").fetchone()[0],
    }
    users = db.execute("SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC LIMIT 100").fetchall()
    listings = db.execute("SELECT l.*, u.name AS seller_name FROM waste_listings l JOIN users u ON u.id = l.seller_id ORDER BY l.created_at DESC LIMIT 100").fetchall()
    return render_template("features.html", tool="admin", admin_stats=stats, admin_users=users, admin_listings=listings)


@app.route("/admin/listings/<int:listing_id>/status", methods=["POST"])
@admin_required
def admin_listing_status(listing_id):
    status = request.form.get("status", "")
    if status not in {"available", "collected"}:
        abort(400)
    db = get_db()
    listing = db.execute("SELECT * FROM waste_listings WHERE id = ?", (listing_id,)).fetchone()
    if listing is None:
        abort(404)
    db.execute("UPDATE waste_listings SET status = ? WHERE id = ?", (status, listing_id))
    db.commit()
    notify_user(db, listing["seller_id"], "Listing moderated", f"An administrator changed '{listing['title']}' status to {status}.", url_for("dashboard"))
    db.commit()
    flash("Listing status updated by admin.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/<int:user_id>/role", methods=["POST"])
@admin_required
def admin_user_role(user_id):
    role = request.form.get("role", "")
    if role not in {"member", "admin"} or user_id == current_user()["id"]:
        abort(400)
    db = get_db()
    user = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    db.commit()
    flash("User role updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.errorhandler(413)
def file_too_large(_error):
    flash("That image is too large. Maximum upload size is 5 MB.", "error")
    return redirect(request.referrer or url_for("create_listing"))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")
