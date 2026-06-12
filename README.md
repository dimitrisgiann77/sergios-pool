# CONDIAN HOTELS — Water & Pool Log

Web εφαρμογή καθημερινής παρακολούθησης για τα ξενοδοχεία CONDIAN. Τρεις ενότητες:

- **Νερά Χρήσης (Water Log):** CLO₂, θερμοκρασία, pH — για το Sergios Hotel.
- **Πισίνες (Pool Log):** ελεύθερο/συνδεδεμένο χλώριο, pH, θερμοκρασία, θολότητα,
  κυανουρικό οξύ, αλκαλικότητα, ORP — για **πολλές πισίνες σε πολλά ξενοδοχεία/σημεία**.
- **AI Βοηθός Πισίνας:** ψηφιακός βοηθός για χημεία, δοσολογία, καθαρισμό και ελέγχους.

Το προσωπικό καταγράφει μετρήσεις πρωί/απόγευμα, αποθηκεύονται σε βάση δεδομένων και
αποστέλλεται αυτόματα email αναφορά με έλεγχο ορίων (OK / ΠΡΟΣΟΧΗ).

## Τεχνολογίες

- **Backend:** Flask + Flask-SQLAlchemy
- **Βάση:** PostgreSQL (production) / SQLite (τοπικά)
- **Email:** SMTP (SSL)
- **AI:** Anthropic ή OpenAI (provider-agnostic, μέσω env)
- **Deploy:** Railway (gunicorn)
- **Γλώσσες:** Ελληνικά / Αγγλικά

## Δομή

```
app.py             # Backend: routes, μοντέλα, email, AI assistant
requirements.txt   # Python εξαρτήσεις
railway.json       # Ρυθμίσεις deploy στο Railway
static/            # app.js (νερά), pools.js (πισίνες), style.css
templates/
  login.html
  app.html / edit.html / dashboard.html               # Νερά Χρήσης
  pools.html / pool_edit.html / pools_dashboard.html   # Πισίνες
  assistant.html                                       # AI Βοηθός
```

## Πισίνες — μοντέλο & όρια

Δομή δεδομένων: **Ξενοδοχείο → Πισίνα → Μέτρηση**. Ο admin προσθέτει ξενοδοχεία και
πισίνες (με όγκο m³) από το `/pools/dashboard`. Κάθε πισίνα έχει μία επίσημη καταγραφή
ανά ημέρα/περίοδο (πρωί/απόγευμα).

Προεπιλεγμένα όρια (στο `POOL_LIMITS` του `app.py`, εύκολα ρυθμίσιμα):

| Παράμετρος | Όριο |
|---|---|
| Ελεύθερο χλώριο | 0.4–1.5 mg/L |
| Συνδεδεμένο χλώριο | ≤ 0.5 mg/L |
| pH | 7.2–7.8 |
| Θερμοκρασία | ≤ 32 °C |
| Θολότητα | ≤ 1 NTU |
| Κυανουρικό οξύ | ≤ 75 mg/L (πρωί) |
| Ολική αλκαλικότητα | 80–120 mg/L (πρωί) |
| ORP / Redox | ≥ 650 mV (πρωί) |

Τα κυανουρικό/αλκαλικότητα/ORP καταγράφονται μόνο το πρωί (περιοδικά).

## Τοπική εκτέλεση

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # συμπλήρωσε τις τιμές
python app.py
```

Άνοιξε http://localhost:5000

## Μεταβλητές περιβάλλοντος

Δες το `.env.example`. Βασικές: `SECRET_KEY`, `DATABASE_URL`, `EMAIL_FROM`, `EMAIL_PASSWORD`.
Για τον AI βοηθό: `ANTHROPIC_API_KEY` ή `OPENAI_API_KEY` (προαιρετικά `AI_PROVIDER`, `AI_MODEL`).

## Προεπιλεγμένοι χρήστες (πρώτη εκκίνηση)

Δημιουργούνται αυτόματα στην πρώτη εκτέλεση (`init_db`). **Άλλαξε τους κωδικούς μετά την πρώτη είσοδο.**

| Username  | Ρόλος  |
|-----------|--------|
| admin     | admin  |
| giannhs   | admin  |
| xypakis   | staff  |

## Όρια μετρήσεων (Νερά Χρήσης)

- **CLO₂:** 1.0–2.0 ppm
- **Θερμοκρασία δεξαμενής:** ≤ 20 °C
- **ΖΝΧ αναχώρηση:** ≥ 60 °C, **επιστροφή:** ≥ 50 °C
- **Ζεστό νερό σημείων:** ≥ 50 °C

## AI Βοηθός Πισίνας

Ψηφιακός βοηθός (σελίδα `/assistant`) που βοηθά το προσωπικό σε χημεία νερού, δοσολογία,
καθαρισμό και ελέγχους εξοπλισμού. Διαβάζει αυτόματα τις τελευταίες μετρήσεις και τον
όγκο της επιλεγμένης πισίνας από τη βάση.

**Ενεργοποίηση:** βάλε στο Railway (Variables) ένα από τα `ANTHROPIC_API_KEY` ή
`OPENAI_API_KEY`. Προαιρετικά `AI_PROVIDER` (auto/anthropic/openai) και `AI_MODEL`.
Χωρίς key, η σελίδα λειτουργεί αλλά ενημερώνει ότι ο βοηθός δεν έχει ρυθμιστεί.

## Σημειώσεις ασφάλειας

Πριν από παραγωγική χρήση συνιστάται: μεταφορά όλων των κωδικών/κλειδιών σε μεταβλητές
περιβάλλοντος, προσθήκη προστασίας CSRF, και μετατροπή των ενεργειών διαγραφής σε POST.
Ο AI βοηθός δεν αντικαθιστά πιστοποιημένο τεχνικό ή τη νομοθεσία.

## v5 — CONDIAN branding & νέες λειτουργίες

- **CONDIAN branding**: επίσημα λογότυπα (`static/img/`), παλέτα navy/gold, fonts DejaVu.
- **PDF export**: branded ημερήσια αναφορά πισινών — κουμπί στο pool dashboard ή `/pools/report.pdf?date=YYYY-MM-DD`.
- **Εγγραφή + προφίλ**: `/register` (με κωδικό `REG_CODE`, ο λογαριασμός μένει σε αναμονή έγκρισης admin), `/profile` για επεξεργασία στοιχείων/κωδικού.
- **Αυτόματες υπενθυμίσεις email**: στις `REMINDER_HOUR` (Europe/Athens) στέλνεται λίστα μη-καταγεγραμμένων πισινών/νερών (κλείδωμα 1/ημέρα ανά worker).
- **Auto-migration**: οι νέες στήλες (`user.email/phone/approved`, `pool.volume_m3`) προστίθενται μόνες τους.

Νέες env: `REG_CODE`, `ENABLE_SCHEDULER`, `REMINDER_HOUR` (δες `.env.example`).
