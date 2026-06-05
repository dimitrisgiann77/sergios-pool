// SERGIOS HOTEL — Pool App JavaScript
// Γλώσσα: ορίζεται από τον server (LANG variable)

const VOL = 90;

// ─── Γλώσσα ──────────────────────────────────────────────────
function applyLanguage() {
  document.querySelectorAll('[data-el]').forEach(el => {
    if (typeof LANG !== 'undefined' && LANG === 'en') {
      el.textContent = el.getAttribute('data-en') || el.textContent;
    } else {
      el.textContent = el.getAttribute('data-el') || el.textContent;
    }
  });
  // Select options
  document.querySelectorAll('select option[data-el]').forEach(opt => {
    opt.textContent = (typeof LANG !== 'undefined' && LANG === 'en')
      ? opt.getAttribute('data-en')
      : opt.getAttribute('data-el');
  });
}

// ─── Ημερομηνία + Καιρός ─────────────────────────────────────
function setDate() {
  const el = document.getElementById('today-date');
  if (!el) return;
  const now = new Date();
  el.textContent = now.toLocaleDateString('el-GR', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
  });
}

async function fetchWeather() {
  try {
    // Χρησιμοποιούμε Open-Meteo (δωρεάν, χωρίς API key)
    const res = await fetch(
      'https://api.open-meteo.com/v1/forecast?latitude=35.298&longitude=25.407&current_weather=true'
    );
    const data = await res.json();
    const temp = data.current_weather?.temperature;
    if (temp !== undefined) {
      document.getElementById('air-temp').textContent = `${temp}°C`;
      const note = temp > 30
        ? (LANG === 'en' ? 'High temp → extra chlorine' : 'Υψηλή θερμοκρ. → αυξημένο χλώριο')
        : (LANG === 'en' ? 'Hersonissos, Crete' : 'Χερσόνησος, Κρήτη');
      document.getElementById('weather-note').textContent = note;
    }
  } catch(e) {
    document.getElementById('air-temp').textContent = '—°C';
  }
}

// ─── Tabs ────────────────────────────────────────────────────
function switchTab(id, btn) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  if (btn) btn.classList.add('active');
}

// ─── Checklist ───────────────────────────────────────────────
function updateChk() {
  const ids = ['c1','c2','c3','c4','c5','c6'];
  const done = ids.filter(id => document.getElementById(id)?.checked).length;
  ids.forEach(id => {
    const lbl = document.getElementById('l-' + id);
    if (lbl) lbl.className = 'chk-label' + (document.getElementById(id).checked ? ' done' : '');
  });
  const pct = Math.round(done / ids.length * 100);
  const bar = document.getElementById('chk-bar');
  const txt = document.getElementById('chk-txt');
  if (bar) bar.style.width = pct + '%';
  if (txt) txt.textContent = `${done}/6`;
}

// ─── Φωτογραφία ──────────────────────────────────────────────
function previewPhoto(input) {
  if (input.files && input.files[0]) {
    const reader = new FileReader();
    reader.onload = e => {
      const preview = document.getElementById('photo-preview');
      const placeholder = document.getElementById('photo-placeholder');
      const area = document.getElementById('photo-area');
      preview.src = e.target.result;
      preview.style.display = 'block';
      placeholder.style.display = 'none';
      area.classList.add('has-photo');
    };
    reader.readAsDataURL(input.files[0]);
  }
}

// ─── Υπολογισμός χημικών ─────────────────────────────────────
function badge(val, low, high, unit, lo, hi) {
  if (isNaN(val) || val === null) return '';
  const loTxt = lo || (LANG==='en' ? 'Low' : 'Χαμηλό');
  const hiTxt = hi || (LANG==='en' ? 'High' : 'Υψηλό');
  if (val < low) return `<div class="sbadge warn"><i class="ti ti-alert-triangle"></i>${loTxt} (${val} ${unit})</div>`;
  if (val > high) return `<div class="sbadge bad"><i class="ti ti-alert-circle"></i>${hiTxt} (${val} ${unit})</div>`;
  return `<div class="sbadge ok"><i class="ti ti-check"></i>${LANG==='en'?'Within range':'Εντός ορίων'} (${val} ${unit})</div>`;
}

function calcChemicals() {
  const ph  = parseFloat(document.getElementById('ph')?.value);
  const alk = parseFloat(document.getElementById('alk')?.value);
  const fc  = parseFloat(document.getElementById('fc')?.value);
  const tc  = parseFloat(document.getElementById('tc')?.value);
  const cya = parseFloat(document.getElementById('cya')?.value);
  const wt  = parseFloat(document.getElementById('wtemp')?.value);
  const sw  = parseInt(document.getElementById('sw')?.value) || 0;
  const clarity  = document.getElementById('clarity')?.value;
  const algd = document.getElementById('algd')?.value === 'true';

  // Status badges
  document.getElementById('ph-st').innerHTML  = badge(ph,  7.2, 7.8, '',
    LANG==='en'?'Low — corrosion risk':'Χαμηλό — κίνδυνος διάβρωσης',
    LANG==='en'?'High — reduces chlorine':'Υψηλό — μειώνει χλώριο');
  document.getElementById('alk-st').innerHTML = badge(alk, 80, 120, 'mg/L');
  document.getElementById('fc-st').innerHTML  = badge(fc,  2.0, 3.0, 'mg/L',
    LANG==='en'?'Insufficient disinfection!':'Ανεπαρκής απολύμανση!',
    LANG==='en'?'Too high':'Πολύ υψηλό');
  document.getElementById('cya-st').innerHTML = badge(cya, 30, 50, 'mg/L',
    LANG==='en'?'Chlorine weak in sunlight':'Χλώριο αδύναμο στον ήλιο',
    LANG==='en'?'Reduces effectiveness':'Μειώνει αποτελεσματικότητα');

  // Δεσμευμένο χλώριο
  if (!isNaN(fc) && !isNaN(tc)) {
    const combined = Math.max(0, tc - fc);
    const box = document.getElementById('combined-box');
    box.style.display = 'flex';
    const col = combined > 0.5 ? '#dc2626' : combined > 0.3 ? '#d97706' : '#16a34a';
    document.getElementById('combined-val').innerHTML =
      `<span style="color:${col}">${combined.toFixed(2)} mg/L</span>`;
    document.getElementById('tc-st').innerHTML = combined > 0.5
      ? `<div class="sbadge bad"><i class="ti ti-alert-circle"></i>${LANG==='en'?'Combined: '+combined.toFixed(2)+' — shock needed!':'Δεσμευμένο: '+combined.toFixed(2)+' — shock!'}</div>`
      : `<div class="sbadge ok"><i class="ti ti-check"></i>${LANG==='en'?'Combined: '+combined.toFixed(2):'Δεσμευμένο: '+combined.toFixed(2)} mg/L</div>`;
  } else {
    document.getElementById('combined-box').style.display = 'none';
    document.getElementById('tc-st').innerHTML = '';
  }

  const hasData = !isNaN(ph)||!isNaN(fc)||!isNaN(alk)||!isNaN(cya);
  document.getElementById('results-section').style.display = hasData ? 'block' : 'none';
  document.getElementById('empty-msg').style.display = hasData ? 'none' : 'flex';
  if (!hasData) return;

  const combined = (!isNaN(fc)&&!isNaN(tc)) ? Math.max(0, tc-fc) : 0;
  const airTemp = typeof AIR_TEMP !== 'undefined' ? AIR_TEMP : 26;
  const highTemp = airTemp > 25 || (!isNaN(wt) && wt > 28);
  const highLoad = sw > 40 || highTemp;
  const minFC = !isNaN(cya) ? Math.max(2.0, cya * 0.075) : 2.0;
  const needsShock = combined > 0.5 || clarity === 'cloudy' || clarity === 'green';

  let html = '';

  // pH
  if (!isNaN(ph)) {
    if (ph > 7.8) {
      const dose = Math.round((ph - 7.4) * VOL * 0.18);
      html += rCard('ti-circle-minus', 'pH−', dose+' g', '#16a34a',
        LANG==='en'
          ? `Lower pH ${ph} → 7.4. Evening or morning (2h before opening).`
          : `Μείωσε pH ${ph} → 7.4. Βράδυ ή πρωί (2h πριν ανοίξει).`, '');
    } else if (ph < 7.2) {
      const dose = Math.round((7.4 - ph) * VOL * 0.14);
      html += rCard('ti-circle-plus', 'pH+', dose+' g', '#185FA5',
        LANG==='en' ? `Raise pH ${ph} → 7.4.` : `Ανύψωσε pH ${ph} → 7.4.`, '');
    } else {
      html += okCard(LANG==='en' ? 'pH within range — no action needed' : 'pH εντός ορίων — δεν χρειάζεται ρύθμιση');
    }
  }

  // CYA
  if (!isNaN(cya)) {
    if (cya > 70) {
      html += `<div class="warn-box"><i class="ti ti-droplet-off" style="flex-shrink:0"></i><span>${LANG==='en'?`CYA high (${cya} mg/L) — dilute pool water with fresh.`:`CYA υψηλό (${cya} mg/L) — αδειάσε μέρος νερού και αναπλήρωσε με φρέσκο.`}</span></div>`;
    } else if (cya < 30) {
      html += `<div class="info-box"><i class="ti ti-sun" style="flex-shrink:0"></i><span>${LANG==='en'?`CYA low (${cya} mg/L) — tablets will gradually raise it.`:`CYA χαμηλό (${cya} mg/L) — οι ταμπλέτες θα το ανεβάσουν σταδιακά.`}</span></div>`;
    } else {
      html += okCard(LANG==='en' ? `CYA within range (${cya} mg/L)` : `CYA εντός ορίων (${cya} mg/L)`);
    }
  }

  // Χλώριο
  if (!isNaN(fc)) {
    if (needsShock) {
      const dose = VOL * 10;
      const reasons = [];
      if (combined > 0.5) reasons.push(LANG==='en' ? `combined chlorine ${(tc-fc).toFixed(2)} mg/L` : `δεσμευμένο χλώριο ${(tc-fc).toFixed(2)} mg/L`);
      if (clarity==='cloudy') reasons.push(LANG==='en' ? 'cloudy water' : 'θολό νερό');
      if (clarity==='green') reasons.push(LANG==='en' ? 'algae' : 'άλγη');
      html += rCard('ti-bolt', 'Astral Trichloro Powder — SHOCK', dose+' g', '#dc2626',
        LANG==='en'
          ? `Due to: ${reasons.join(', ')}. Dissolve in water, pour into pool deep end. Evening only, no swimmers.`
          : `Λόγω: ${reasons.join(', ')}. Διάλυσε σε νερό, ρίξε στη βαθύτερη πλευρά. Βράδυ, χωρίς κολυμβητές.`,
        LANG==='en' ? 'Label: 10g/m³ × 90m³ · Re-entry after 12–14 hours' : 'Ετικέτα: 10g/m³ × 90m³ · Είσοδος μετά 12–14 ώρες');
    } else {
      const tabs = (fc < minFC || highLoad) ? 2 : 1;
      const reason = fc < minFC
        ? (LANG==='en' ? `Free Chlorine low (${fc} mg/L)` : `Free Chlorine χαμηλό (${fc} mg/L)`)
        : (highLoad ? (LANG==='en' ? `High temp / load (${airTemp}°C)` : `Υψηλή θερμοκρ./φορτίο (${airTemp}°C)`) : 'maintenance');
      html += rCard('ti-plus', 'Aqua Clor Ταμπλέτες 200g', tabs+' τεμ.', '#185FA5',
        reason + '. ' + (tabs===2
          ? (LANG==='en' ? '1 tablet in each skimmer.' : '1 ταμπλέτα σε κάθε skimmer.')
          : (LANG==='en' ? '1 tablet in one skimmer.' : '1 ταμπλέτα σε έναν skimmer.')),
        LANG==='en' ? 'Label: 1 tablet/20m³ · 2 skimmers' : 'Ετικέτα: 1 ταμπλέτα/20m³ · 2 skimmer');
    }
  }

  // Alkalinity
  if (!isNaN(alk)) {
    if (alk < 80) {
      const dose = Math.round((80-alk)*VOL*0.015);
      html += rCard('ti-arrow-up', 'Sodium Bicarbonate', dose+' g', '#d97706',
        LANG==='en' ? `Alkalinity low (${alk} → target 80–120 mg/L).` : `Alkalinity χαμηλή (${alk} → στόχος 80–120 mg/L).`, '');
    } else if (alk > 150) {
      html += `<div class="warn-box"><i class="ti ti-arrow-down" style="flex-shrink:0"></i><span>${LANG==='en'?`Alkalinity high (${alk} mg/L) — reduce with pH−.`:`Alkalinity υψηλή (${alk} mg/L) — μείωσε με pH−.`}</span></div>`;
    } else {
      html += okCard(LANG==='en' ? `Alkalinity within range (${alk} mg/L)` : `Alkalinity εντός ορίων (${alk} mg/L)`);
    }
  }

  // Αλγοκτόνο
  if (!algd) {
    const dose = Math.round(375 * VOL / 50);
    html += rCard('ti-plant', 'Aqua Clor Algicide Super', dose+' ml', '#16a34a',
      LANG==='en'
        ? 'Weekly dose. End of day, near water inlets, filtration running.'
        : 'Εβδομαδιαία δόση. Τέλος ημέρας, κοντά στις εισόδους νερού.',
      LANG==='en' ? 'Label: 375ml/50m³/week' : 'Ετικέτα: 375ml/50m³/εβδομάδα');
  } else {
    html += okCard(LANG==='en' ? 'Algicide done this week' : 'Αλγοκτόνο έχει γίνει αυτή την εβδομάδα');
  }

  // CYA υπενθύμιση
  if (!isNaN(cya) && cya >= 30 && cya <= 70) {
    html += `<div class="info-box"><i class="ti ti-info-circle" style="flex-shrink:0"></i><span>${LANG==='en'?'Measure CYA <b>once/week</b> — stop tablets temporarily if it reaches 60+ mg/L.':'Μέτρα CYA <b>1 φορά/εβδομάδα</b> — αν φτάσει 60+ mg/L σταμάτα τις ταμπλέτες προσωρινά.'}</span></div>`;
  }

  if (!html) html = okCard(LANG==='en' ? 'All within range — great job!' : 'Όλα εντός ορίων — καλή δουλειά!');
  document.getElementById('results-content').innerHTML = html;
}

function rCard(icon, name, dose, color, note, src) {
  const s = src ? `<div class="rcard-src"><i class="ti ti-file-text"></i> ${src}</div>` : '';
  return `<div class="rcard">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
      <i class="ti ${icon}" style="font-size:18px;color:${color}"></i>
      <span class="rcard-name">${name}</span>
    </div>
    <div class="rcard-dose" style="color:${color}">${dose}</div>
    <div class="rcard-note">${note}</div>${s}
  </div>`;
}
function okCard(msg) {
  return `<div class="ok-card"><i class="ti ti-check" style="font-size:18px"></i>${msg}</div>`;
}

// ─── Υποβολή φόρμας ──────────────────────────────────────────
async function submitForm() {
  const btn = document.getElementById('submit-btn');
  const msgDiv = document.getElementById('submit-msg');
  btn.disabled = true;
  btn.innerHTML = `<i class="ti ti-loader"></i> ${LANG==='en'?'Submitting...':'Αποστολή...'}`;

  const form = document.getElementById('pool-form');
  const formData = new FormData(form);

  // Προσθήκη checklist values
  ['check_walls','check_backwash','check_pump','check_skimmer','check_waterline','check_prefilter'].forEach(name => {
    const el = document.querySelector(`[name="${name}"]`);
    formData.set(name, el && el.checked ? 'true' : 'false');
  });

  // Παρατηρήσεις
  const notes = document.getElementById('notes');
  if (notes) formData.set('notes', notes.value);

  // Φωτογραφία
  const photoInput = document.getElementById('photo-input');
  if (photoInput && photoInput.files[0]) {
    formData.set('photo', photoInput.files[0]);
  }

  // algicide
  const algd = document.getElementById('algd');
  if (algd) formData.set('algicide_done', algd.value === 'true' ? 'true' : 'false');

  try {
    const res = await fetch('/submit', { method: 'POST', body: formData });
    const data = await res.json();
    msgDiv.style.display = 'block';
    msgDiv.className = 'submit-msg ' + (data.success ? 'success' : 'error');
    msgDiv.textContent = data.message;
    if (data.success) {
      btn.innerHTML = `<i class="ti ti-check"></i> ${LANG==='en'?'Submitted!':'Υποβλήθηκε!'}`;
    } else {
      btn.disabled = false;
      btn.innerHTML = `<i class="ti ti-send"></i> ${LANG==='en'?'Submit report':'Υποβολή αναφοράς'}`;
    }
  } catch(e) {
    msgDiv.style.display = 'block';
    msgDiv.className = 'submit-msg error';
    msgDiv.textContent = LANG==='en' ? 'Connection error. Try again.' : 'Σφάλμα σύνδεσης. Δοκίμασε ξανά.';
    btn.disabled = false;
    btn.innerHTML = `<i class="ti ti-send"></i> ${LANG==='en'?'Submit report':'Υποβολή αναφοράς'}`;
  }
}

// ─── Οδηγίες ─────────────────────────────────────────────────
const PROCEDURES = [
  {
    num: 1,
    el: { title: 'Μέτρηση με το Pool Line', tag: 'Καθημερινά — πρωί',
      steps: ['Πάρε νερό σε βάθος 30–40 cm, μακριά από skimmer και εισόδους.',
        'Μέτρα με τη σειρά: pH → Free Chlorine → Total Chlorine → Alkalinity → CYA.',
        'Καθάρισε το όργανο με καθαρό νερό μεταξύ μετρήσεων.',
        'Κατέγραψε τις τιμές στην εφαρμογή αμέσως.'],
      warn: 'Μην μετράς αμέσως μετά από προσθήκη χημικών — περίμενε τουλάχιστον 2 ώρες. Έλεγχε την ημερομηνία λήξης των reagents.' },
    en: { title: 'Pool Line measurement', tag: 'Daily — morning',
      steps: ['Take water sample 30–40 cm deep, away from skimmers and inlets.',
        'Measure in order: pH → Free Chlorine → Total Chlorine → Alkalinity → CYA.',
        'Rinse instrument with clean water between measurements.',
        'Record values in the app immediately.'],
      warn: 'Do not measure immediately after adding chemicals — wait at least 2 hours. Check reagent expiry dates.' }
  },
  {
    num: 2,
    el: { title: 'Τοποθέτηση ταμπλετών στον skimmer', tag: 'Καθημερινά — πρωί',
      steps: ['Φόρεσε γάντια.',
        'Άνοιξε το καπάκι του πρώτου skimmer.',
        'Έλεγξε αν έχει διαλυθεί η προηγούμενη ταμπλέτα — αν υπάρχει υπόλειμμα, μην προσθέσεις νέα.',
        'Τοποθέτησε 1 ταμπλέτα στο καλάθι.',
        'Επανάλαβε στον δεύτερο skimmer.'],
      warn: 'Ποτέ μην αγγίζεις τις ταμπλέτες με γυμνά χέρια. Αν το Free Chlorine είναι πάνω από 3.0 mg/L, μην τοποθετήσεις ταμπλέτα σήμερα.' },
    en: { title: 'Placing tablets in skimmer', tag: 'Daily — morning',
      steps: ['Wear gloves.',
        'Open the first skimmer lid.',
        'Check if previous tablet has dissolved — if residue remains, do not add new one.',
        'Place 1 tablet in the basket.',
        'Repeat for the second skimmer.'],
      warn: 'Never touch tablets with bare hands. If Free Chlorine is above 3.0 mg/L, do not add a tablet today.' }
  },
  {
    num: 3,
    el: { title: 'Shock treatment — σκόνη χλωρίου', tag: "Βράδυ — κατ' ανάγκη",
      steps: ['Φόρεσε γάντια, μάσκα και γυαλιά.',
        'Γέμισε κουβαδάκι με κρύο νερό — ποτέ ζεστό.',
        'Ζύγισε την ποσότητα που υποδεικνύει η εφαρμογή.',
        'Ρίξε τη σκόνη μέσα στο νερό — ποτέ το αντίθετο.',
        'Ανακάτεψε μέχρι να διαλυθεί πλήρως.',
        'Ρίξε στην πισίνα σε διάφορα σημεία στη βαθύτερη πλευρά, μακριά από τα τοιχία.',
        'Άφησε τη φίλτρανση να δουλεύει όλη τη νύχτα.',
        'Επόμενο πρωί πριν ανοίξει: Free Chlorine < 3.0 mg/L για είσοδο κολυμβητών.'],
      warn: 'Κλειστή πισίνα 12–14 ώρες μετά. Ποτέ αδιάλυτη σκόνη απευθείας στην πισίνα. Ποτέ ανάμιξη με άλλα χημικά — κίνδυνος φωτιάς.' },
    en: { title: 'Shock treatment — chlorine powder', tag: 'Evening — when needed',
      steps: ['Wear gloves, mask, and goggles.',
        'Fill bucket with cold water — never hot.',
        'Weigh the amount shown by the app.',
        'Add powder to water — never the reverse.',
        'Stir until fully dissolved.',
        'Pour into pool at several points in the deep end, away from walls.',
        'Leave filtration running all night.',
        'Next morning before opening: Free Chlorine < 3.0 mg/L before allowing swimmers.'],
      warn: 'Pool closed 12–14 hours after shock. Never add undissolved powder directly to pool. Never mix with other chemicals — fire hazard.' }
  },
  {
    num: 4,
    el: { title: 'Προσθήκη pH−', tag: 'Βράδυ ή πρωί (2h πριν ανοίξει)',
      steps: ['Φόρεσε γάντια και γυαλιά.',
        'Μέτρα την ποσότητα που υποδεικνύει η εφαρμογή.',
        'Βεβαιώσου ότι η φίλτρανση είναι σε πλήρη λειτουργία.',
        'Ρίξε αργά και σταδιακά σε ένα σκιερό σημείο.',
        'Επανάμετρε το pH μετά από 2 ώρες — στόχος 7.2–7.8.'],
      warn: 'Μην κολυμπάτε για τουλάχιστον 1 ώρα μετά. Ποτέ μην αναμιγνύεις pH− με χλώριο — κίνδυνος τοξικών αερίων.' },
    en: { title: 'Adding pH−', tag: 'Evening or morning (2h before opening)',
      steps: ['Wear gloves and goggles.',
        'Measure the amount shown by the app.',
        'Make sure filtration is running at full capacity.',
        'Pour slowly and gradually in a shaded spot.',
        'Re-measure pH after 2 hours — target 7.2–7.8.'],
      warn: 'No swimming for at least 1 hour after adding. Never mix pH− with chlorine — toxic gas risk.' }
  },
  {
    num: 5,
    el: { title: 'Backwash φίλτρου', tag: 'Καθημερινά',
      steps: ['Αντλία OFF.','Πολυβάνα → BACKWASH.',
        'Αντλία ON — μέχρι να καθαρίσει το γυαλάκι.',
        'Αντλία OFF.','Πολυβάνα → RINSE.',
        'Αντλία ON για 20–30 δευτερόλεπτα.',
        'Αντλία OFF.','Πολυβάνα → FILTER.','Αντλία ON (AUTO).'],
      warn: 'Ποτέ μην αλλάζεις θέση στην πολυβάνα με την αντλία σε λειτουργία.' },
    en: { title: 'Filter backwash', tag: 'Daily',
      steps: ['Pump OFF.','Multiport valve → BACKWASH.',
        'Pump ON — until sight glass clears.',
        'Pump OFF.','Multiport valve → RINSE.',
        'Pump ON for 20–30 seconds.',
        'Pump OFF.','Multiport valve → FILTER.','Pump ON (AUTO).'],
      warn: 'Never change valve position while pump is running.' }
  },
  {
    num: 6,
    el: { title: 'Καθαρισμός προφίλτρων', tag: 'Καθημερινά — πρωί',
      steps: ['Σβήσε την αντλία.',
        'Ξεβίδωσε το καπάκι του προφίλτρου αργά.',
        'Βγάλε το καλάθι και άδειασε τα υπολείμματα.',
        'Ξέπλυνε με νερό μέχρι να καθαριστεί.',
        'Τοποθέτησε πίσω και βίδωσε το καπάκι.',
        'Άναψε την αντλία και έλεγξε για διαρροές.'],
      warn: 'Ποτέ μην ανοίγεις το προφίλτρο με την αντλία σε λειτουργία. Αν η φλάντζα είναι φθαρμένη, αντικατέστησέ την αμέσως.' },
    en: { title: 'Pre-filter cleaning', tag: 'Daily — morning',
      steps: ['Turn off the pump.',
        'Slowly unscrew the pre-filter lid.',
        'Remove basket and empty debris.',
        'Rinse with water until clean.',
        'Replace basket and tighten lid.',
        'Turn on pump and check for leaks.'],
      warn: 'Never open pre-filter with pump running. Replace gasket immediately if worn.' }
  },
  {
    num: 7,
    el: { title: 'Έλεγχος αντλίας και κυκλοφορίας', tag: 'Καθημερινά — πρωί',
      steps: ['Έλεγξε οπτικά για διαρροές νερού.',
        'Άκου την αντλία — ομαλός ήχος χωρίς δονήσεις.',
        'Σημείωσε την τιμή του πιεσόμετρου στις παρατηρήσεις.',
        'Έλεγξε τις εισόδους νερού — καλή ροή.',
        'Έλεγξε για φυσαλίδες αέρα στην αντλία.'],
      warn: 'Αν η αντλία κάνει ασυνήθιστο θόρυβο ή υπάρχει διαρροή, σβήσε αμέσως και ενημέρωσε τον υπεύθυνο. Ποτέ μην αφήνεις αντλία χωρίς νερό.' },
    en: { title: 'Pump and circulation check', tag: 'Daily — morning',
      steps: ['Visually check for water leaks.',
        'Listen to pump — smooth sound, no vibrations.',
        'Note pressure gauge reading in observations.',
        'Check water inlets — good flow.',
        'Check for air bubbles in the pump.'],
      warn: 'If pump makes unusual noise or there is a leak, turn off immediately and notify supervisor. Never run pump dry.' }
  },
  {
    num: 8,
    el: { title: 'Έλεγχος και καθαρισμός skimmer', tag: 'Καθημερινά — πρωί',
      steps: ['Άνοιξε το καπάκι του πρώτου skimmer.',
        'Έλεγξε υπόλειμμα ταμπλέτας.',
        'Βγάλε και καθάρισε το καλάθι.',
        'Έλεγξε ότι το flap κινείται ελεύθερα.',
        'Έλεγξε επίπεδο νερού — στη μέση του skimmer.',
        'Επανάλαβε στον δεύτερο skimmer.'],
      warn: 'Αν το επίπεδο νερού είναι κάτω από το κατώτατο όριο, σβήσε αμέσως την αντλία και αναπλήρωσε νερό.' },
    en: { title: 'Skimmer check and cleaning', tag: 'Daily — morning',
      steps: ['Open first skimmer lid.',
        'Check for tablet residue.',
        'Remove and clean basket.',
        'Check flap moves freely.',
        'Check water level — should be at mid-skimmer.',
        'Repeat for second skimmer.'],
      warn: 'If water level is below the skimmer minimum, turn off pump immediately and refill pool.' }
  },
  {
    num: 9,
    el: { title: 'Καθαρισμός ίσαλης γραμμής', tag: 'Καθημερινά — πρωί',
      steps: ['Χρησιμοποίησε Magic Eraser με νερό πισίνας — χωρίς χημικά.',
        'Τρίψε κυκλικά κατά μήκος όλης της ίσαλης γραμμής.',
        'Για επίμονους λεκέδες: δοκίμασε ελαφρόπετρα με νερό πισίνας.',
        'Αν η ελαφρόπετρα δεν δουλέψει: χρησιμοποίησε Astral Pool Waterline Cleaner.'],
      warn: 'Ποτέ μην χρησιμοποιείς σύρμα ή μεταλλικό τριφτάρι — χαράζει μόνιμα τα πορσελάνινα πλακίδια.' },
    en: { title: 'Waterline cleaning', tag: 'Daily — morning',
      steps: ['Use Magic Eraser with pool water — no chemicals.',
        'Scrub in circular motions along the entire waterline.',
        'For stubborn stains: try pumice stone with pool water.',
        'If pumice stone does not work: use Astral Pool Waterline Cleaner.'],
      warn: 'Never use steel wool or metal scrubbers — permanently scratches porcelain tiles.' }
  },
  {
    num: 10,
    el: { title: 'Καθαρισμός τοιχίων και πυθμένα', tag: 'Καθημερινά — πρωί',
      steps: ['Βούρτσισε τα τοιχία κυκλικά από πάνω προς τα κάτω. Έμφαση στις γωνίες.',
        'Άφησε τα σωματίδια να κατακαθίσουν 5–10 λεπτά.',
        'Σβήσε την αντλία.',
        'Γύρισε την πολυβάνα στη θέση WASTE.',
        'Άναψε την αντλία.',
        'Συνδέστε τη σκούπα στο ειδικό στόμιο.',
        'Κινήσου αργά σε παράλληλες γραμμές από τη μακρινή άκρη προς το στόμιο.',
        'Αντλία OFF → Πολυβάνα → FILTER → Αντλία ON (AUTO).',
        'Έλεγξε και αναπλήρωσε επίπεδο νερού αν χρειάζεται.'],
      warn: 'Ποτέ μην αλλάζεις θέση στην πολυβάνα με την αντλία σε λειτουργία. Στη θέση WASTE χάνεται νερό — μην αφήσεις το επίπεδο να πέσει πολύ.' },
    en: { title: 'Wall and floor cleaning', tag: 'Daily — morning',
      steps: ['Brush walls in circular motions top to bottom. Focus on corners.',
        'Allow particles to settle for 5–10 minutes.',
        'Turn off pump.',
        'Set multiport valve to WASTE.',
        'Turn on pump.',
        'Connect vacuum to the dedicated wall fitting.',
        'Move slowly in parallel lines from far end towards fitting.',
        'Pump OFF → Valve → FILTER → Pump ON (AUTO).',
        'Check and refill water level if needed.'],
      warn: 'Never change valve position while pump is running. WASTE position uses water — do not let level drop too low.' }
  }
];

function buildProcedures() {
  const container = document.getElementById('procs-container');
  if (!container) return;
  container.innerHTML = '';
  PROCEDURES.forEach(p => {
    const lang = (typeof LANG !== 'undefined' && LANG === 'en') ? p.en : p.el;
    const div = document.createElement('div');
    div.className = 'proc-card';
    div.innerHTML = `
      <div class="proc-header" onclick="toggleProc(this)">
        <div class="proc-num">${p.num}</div>
        <div class="proc-title">${lang.title}</div>
        <div class="proc-tag">${lang.tag}</div>
        <i class="ti ti-chevron-down proc-chevron"></i>
      </div>
      <div class="proc-body">
        <div class="proc-body-title">${LANG==='en'?'Steps:':'Βήματα:'}</div>
        <ol>${lang.steps.map(s=>`<li>${s}</li>`).join('')}</ol>
        <div class="proc-warn"><i class="ti ti-alert-triangle"></i> ${lang.warn}</div>
      </div>`;
    container.appendChild(div);
  });
}

function toggleProc(header) {
  const body = header.nextElementSibling;
  const icon = header.querySelector('.proc-chevron');
  const isOpen = body.classList.contains('open');
  document.querySelectorAll('.proc-body').forEach(b => b.classList.remove('open'));
  document.querySelectorAll('.proc-chevron').forEach(i => i.style.transform = '');
  if (!isOpen) {
    body.classList.add('open');
    icon.style.transform = 'rotate(180deg)';
  }
}

// ─── Init ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  applyLanguage();
  setDate();
  fetchWeather();
  buildProcedures();
  updateChk();
});
