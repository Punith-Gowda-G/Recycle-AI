"""Add safe, clearly labelled demo data for trying RecycleLink smart tools.

Run: python seed_demo.py
This is idempotent and never deletes or overwrites existing records.
Demo accounts (change passwords after local testing):
  seller.demo@recyclelink.local / DemoPass123!
  recycler.demo@recyclelink.local / DemoPass123!
  admin.demo@recyclelink.local / DemoPass123!
"""
import sqlite3
from datetime import date, timedelta
from werkzeug.security import generate_password_hash
import app as recycle_app


def seed_demo_data():
    recycle_app.init_db()
    db = sqlite3.connect(recycle_app.DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    accounts = [
        ("Demo Seller", "seller.demo@recyclelink.local", "member"),
        ("Demo Recycler", "recycler.demo@recyclelink.local", "member"),
        ("Demo Admin", "admin.demo@recyclelink.local", "admin"),
    ]
    ids = {}
    for name, email, role in accounts:
        row = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            ids[email] = row["id"]
            if role == "admin":
                db.execute("UPDATE users SET role='admin' WHERE id=?", (row["id"],))
        else:
            cur = db.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                             (name, email, generate_password_hash("DemoPass123!"), role))
            ids[email] = cur.lastrowid

    seller = ids["seller.demo@recyclelink.local"]
    recycler = ids["recycler.demo@recyclelink.local"]
    admin = ids["admin.demo@recyclelink.local"]
    samples = [
        (seller, "Clean cardboard boxes", "Cardboard", "Dry boxes ready for recycling", 25, "kg", 12.5, "Jayanagar, Bengaluru", 12.9250, 77.5838),
        (seller, "Extra cardboard offcuts", "Cardboard", "Clean cardboard offcuts for reuse", 15, "kg", 11.0, "Jayanagar, Bengaluru", 12.9270, 77.5810),
        (seller, "Sorted PET plastic bottles", "Plastic", "Clean sorted PET bottles", 18, "kg", 22.0, "JP Nagar, Bengaluru", 12.9063, 77.5857),
        (seller, "Old newspapers bundle", "Paper", "Bundled newspaper and office paper", 30, "kg", 10.0, "Basavanagudi, Bengaluru", 12.9421, 77.5681),
        (seller, "Aluminium scrap pieces", "Metal", "Separated aluminium scrap", 8, "kg", 95.0, "Banashankari, Bengaluru", 12.9255, 77.5468),
        (seller, "Mixed glass bottles", "Glass", "Rinsed glass bottles", 12, "kg", 5.0, "JP Nagar, Bengaluru", 12.9081, 77.5900),
    ]
    for row in samples:
        exists = db.execute("SELECT id FROM waste_listings WHERE seller_id=? AND title=?", (row[0], row[1])).fetchone()
        if not exists:
            db.execute("""INSERT INTO waste_listings(seller_id,title,material,description,quantity,unit,price_per_unit,location,latitude,longitude,status)
                VALUES(?,?,?,?,?,?,?,?,?,?, 'available')""", row)
    recycler_sample = (recycler, "Reusable plastic containers", "Plastic", "Clean containers available for reuse", 10, "kg", 20.0, "Jayanagar, Bengaluru", 12.9290, 77.5800)
    if not db.execute("SELECT id FROM waste_listings WHERE seller_id=? AND title=?", (recycler, recycler_sample[1])).fetchone():
        db.execute("""INSERT INTO waste_listings(seller_id,title,material,description,quantity,unit,price_per_unit,location,latitude,longitude,status)
            VALUES(?,?,?,?,?,?,?,?,?,?, 'available')""", recycler_sample)

    # Add one completed pickup so impact, reviews and price-related flows can be demonstrated.
    listing = db.execute("SELECT id, title FROM waste_listings WHERE seller_id=? AND title='Clean cardboard boxes'", (seller,)).fetchone()
    pickup = db.execute("SELECT id FROM pickup_requests WHERE listing_id=? AND recycler_id=?", (listing["id"], recycler)).fetchone()
    if not pickup:
        cur = db.execute("""INSERT INTO pickup_requests(listing_id,recycler_id,pickup_date,message,status)
            VALUES(?,?,?,?, 'completed')""", (listing["id"], recycler, (date.today()-timedelta(days=2)).isoformat(), "Seeded demo collection"))
        pickup_id = cur.lastrowid
        db.execute("UPDATE waste_listings SET status='collected' WHERE id=?", (listing["id"],))
    else:
        pickup_id = pickup["id"]
        db.execute("UPDATE pickup_requests SET status='completed' WHERE id=?", (pickup_id,))
        db.execute("UPDATE waste_listings SET status='collected' WHERE id=?", (listing["id"],))

    # Keep one available cardboard listing for marketplace matching and price examples.
    db.execute("UPDATE waste_listings SET status='available' WHERE seller_id=? AND title='Clean cardboard boxes' AND id != ?", (seller, listing["id"]))
    notification = db.execute("SELECT id FROM notifications WHERE user_id=? AND title='Welcome to RecycleLink demo data'", (recycler,)).fetchone()
    if not notification:
        db.execute("INSERT INTO notifications(user_id,title,body,link) VALUES(?,?,?,?)",
                   (recycler, "Welcome to RecycleLink demo data", "Demo listings and a completed pickup are ready to explore.", "/features"))
    db.commit()
    counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for table in ("users", "waste_listings", "pickup_requests", "notifications")}
    db.close()
    return counts


if __name__ == "__main__":
    print("Demo data ready:", seed_demo_data())
    print("Demo login: seller.demo@recyclelink.local / DemoPass123!")
    print("Demo login: recycler.demo@recyclelink.local / DemoPass123!")
    print("Demo admin: admin.demo@recyclelink.local / DemoPass123!")
    print("Local demo only. Change/remove these accounts before deployment.")
