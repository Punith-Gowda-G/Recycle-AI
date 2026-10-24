# RecycleLink — Waste Marketplace ♻️

RecycleLink is a Flask + SQLite marketplace that helps people list recyclable materials and lets recyclers request pickups. This portfolio version includes authentication, material listings, search and filters, seller dashboards, pickup workflows, in-app notifications, reviews, admin moderation, smart matching, a price estimator, an AI classification API integration, an environmental-impact estimate, and a pickup-route heuristic.

## Features

- Register, log in, and log out with hashed passwords.
- Create and delete waste listings with optional photos.
- Search listings by title, description, or location; filter by material; sort by price or quantity.
- Request a pickup with a preferred date and message.
- Sellers can accept or reject pending pickup requests.
- Accepted pickups can be marked completed by either party (for this demo, one confirmation completes the pickup).
- Personal dashboard with listing counts, pickup requests, and a monthly listing chart.
- **AI waste image classification:** optional Hugging Face inference API integration; requires a model trained for waste categories and environment configuration.
- **Local AI waste classifier:** train the included `O`/`R` image dataset locally and use the resulting model without Hugging Face credits.
- **Smart matching:** transparent ranking by material, shared location keywords, and the seller's completed pickup history.
- **Price estimator:** uses marketplace history, with a median baseline and optional scikit-learn linear regression when enough examples exist.
- **Environmental impact:** estimated completed kg and illustrative CO₂e factors; not verified environmental claims.
- **Pickup route optimization:** nearest-neighbour heuristic using latitude/longitude and straight-line Haversine distances.
- **Ratings and reviews:** one review per user per completed pickup, with review notifications.
- **Live in-app notifications:** database-backed alerts and browser polling every 15 seconds.
- **Admin dashboard:** user role management and listing moderation; set `ADMIN_EMAIL` to bootstrap an admin.
- CSRF protection for forms, parameterized SQL, upload extension checks, and ownership checks.
- Responsive premium green/white/charcoal UI.

## Requirements

- Python 3.10 or newer
- pip
- Internet connection for Google Fonts and Chart.js CDN (the application itself runs locally without them, but those visual enhancements will not load offline)

## 1. Set up the project

Open a terminal in the `RecycleLink` directory.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` and then run the app with ` .\.venv\Scripts\python.exe app.py`.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2. Configure the secret key

The app has a development fallback secret so it can run immediately on your laptop. Before deployment, set a unique random `SECRET_KEY` in the environment. Do not commit it to GitHub.

### Windows PowerShell

```powershell
$env:SECRET_KEY = "replace-this-with-a-long-random-secret"
```

### macOS / Linux

```bash
export SECRET_KEY="replace-this-with-a-long-random-secret"
```

To use a different SQLite database file, set `DATABASE_PATH` to its path. If not set, the app creates `instance/recyclelink.db` automatically.

### Optional AI classifier and admin setup

Set these environment variables only if you want the AI classifier or admin bootstrap:

```text
HF_API_TOKEN=your_hugging_face_access_token
HF_IMAGE_MODEL=your-username/waste-classification-model
ADMIN_EMAIL=admin@example.com
```

- `HF_IMAGE_MODEL` must be an accessible image-classification model trained for the waste categories you want to detect. A generic image model may return irrelevant labels. Keep the token private and do not commit it.
- `ADMIN_EMAIL` promotes the matching account to admin when the app initializes. Register that account with a strong password. To promote an already-existing account, set `ADMIN_EMAIL` and restart the app.
- The app still runs without the AI token; the AI detection page explains how to configure it.

### Train the local classifier

The application can use a locally trained classifier before trying Hugging Face. The provided dataset archive should contain `DATASET/TRAIN/O`, `DATASET/TRAIN/R`, `DATASET/TEST/O`, and `DATASET/TEST/R` directories:

```powershell
python train_classifier.py "C:\path\to\archive (1).zip"
```

This writes `models/waste_classifier.joblib` and prints test-set accuracy. Once that file exists, the AI detection page uses it automatically. To use a different model path, set `LOCAL_MODEL_PATH`.

## 3. Initialize the database

The application creates its SQLite tables automatically on startup. To initialize the database explicitly, run:

```bash
python -c "from app import init_db; init_db(); print('RecycleLink database initialized.')"
```

Default database: `instance/recyclelink.db`. Tables include `users`, `waste_listings`, `pickup_requests`, `notifications`, `reviews`, and `ai_detections`. Startup performs additive migrations for the listing latitude/longitude fields. Back up the database before making schema changes to an existing project.

No demo account is created by default. A new database is empty, so data-driven tools may initially show empty states. For a local demonstration, run the idempotent sample-data script:

```bash
python seed_demo.py
```

Demo logins (local testing only; do not use these credentials on a public deployment):
- Seller: `seller.demo@recyclelink.local` / `DemoPass123!`
- Recycler: `recycler.demo@recyclelink.local` / `DemoPass123!`
- Admin: `admin.demo@recyclelink.local` / `DemoPass123!`

The script adds sample listings, a completed pickup, and a notification without deleting existing records. AI image detection still requires a working model endpoint and token; the seed script does not fake AI predictions.

## 4. Run locally

```bash
python app.py
```

Open <http://127.0.0.1:5000> in your browser.

### Suggested manual walkthrough

1. Register as a seller.
2. Open **List waste** and publish a listing (try cardboard, plastic, or metal).
3. Log out and register a second account as a recycler.
4. Find the listing in the marketplace and request a pickup for today or a future date.
5. Log out, sign in as the seller, and accept the request from the dashboard.
6. Sign in as either party and mark the accepted pickup completed.
7. Review listing activity and status changes in the dashboard.
8. Run `python seed_demo.py` on a local demo database to populate smart matching, price estimates, environmental impact, and notifications. Route planning uses the prefilled sample coordinates; review the route as straight-line estimates only.
9. Complete a pickup, then open its **Review** link to rate the other party.
10. Configure `ADMIN_EMAIL` to try the admin dashboard. Configure `HF_API_TOKEN` and `HF_IMAGE_MODEL` to call an actual waste-classification model.

## 5. Run tests

```bash
pytest -q
```

The tests use a temporary SQLite database and disable CSRF validation only inside the test configuration. CSRF protection remains enabled for normal app runs. The AI inference endpoint is external and is not called by the automated tests.

## Project structure

```text
RecycleLink/
├── app.py                     # Flask routes, auth, database, workflows, feature integrations
├── requirements.txt
├── README.md
├── .gitignore
├── instance/                   # SQLite DB created at runtime (not committed)
├── models/                     # Reserved for future model separation
├── static/
│   ├── css/style.css           # Responsive UI styles
│   ├── js/main.js              # Navigation, alerts, chart, confirmations
│   └── uploads/                # Listing images (not committed)
├── templates/                  # Jinja templates, including features.html
└── tests/test_app.py
```

## Database overview

- `users`: account name, email, password hash, role, creation time.
- `waste_listings`: seller, title, material, quantity, unit, price, location, image, and availability status.
- `pickup_requests`: listing, recycler, requested pickup date, message, and request status.
- `notifications`: user alerts and read state.
- `reviews`: star rating and comment for completed pickups.
- `ai_detections`: saved model label/confidence (the image itself is not stored by the classifier route).
- `waste_listings.latitude/longitude`: additive fields reserved for future map-enabled listing workflows.

## GitHub upload steps

Create a new empty repository on GitHub (for example, `recyclelink-waste-marketplace`). Do not add a README from GitHub if you already have this one locally.

```bash
git init
git add .
git status
git commit -m "Build RecycleLink waste marketplace"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/recyclelink-waste-marketplace.git
git push -u origin main
```

Replace `YOUR-USERNAME` with your GitHub username. Check `git status` before pushing and ensure `.env`, database files, uploaded photos, and secret keys are not included.

For future work, commit features separately, for example:

```bash
git add app.py templates/ static/
git commit -m "Add marketplace listings and filters"
git push
```

## Important production notes

This is a portfolio/demo project, not a production marketplace. Before real-world use, add rate limiting, email verification and password reset, stricter image-content validation, pagination, backups, logging, and persistent database/storage for deployment. The demo allows either party to confirm pickup completion; production should require confirmation from both sides. SQLite and local uploads require persistent storage on a host such as Render. Never store real secrets in source code.

The AI classifier requires a compatible waste-trained model and may return incorrect predictions. The price estimator is only as reliable as the listings in its dataset. The route planner uses straight-line distances and a nearest-neighbour heuristic, so it is not a replacement for road routing or traffic-aware directions. Environmental factors are illustrative assumptions and must be replaced with documented factors before making sustainability claims. The smart matcher is a rule-based baseline, not a trained AI recommender.

## License

For learning and portfolio use. Add a license file if you want to specify reuse permissions.
