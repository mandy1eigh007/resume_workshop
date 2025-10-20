# app.py — Seattle Tri-County Construction Resume & Pathways
# Streamlit single-file app. No external APIs at runtime.
# Python 3.11 (see runtime.txt). Deps pinned in requirements.txt.

from __future__ import annotations

import io, os, re, json, textwrap
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

import streamlit as st
import pandas as pd

from docxtpl import DocxTemplate
from docx import Document as DocxReader
from docx import Document as DocxWriter
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

from pypdf import PdfReader

# Optional: pdfminer is better for text-y PDFs; pypdf is our fallback
try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
except Exception:
    pdfminer_extract_text = None

# ─────────────────────────────────────────────────────────
# App config
# ─────────────────────────────────────────────────────────
st.set_page_config(page_title="Resume & Pathways — Seattle Tri-County", layout="wide")

SUPPORTING_DOCS = {
    "JOB_MASTER": "Job_History_Master.docx",
    "PLAYBOOK": "Stand_Out_Playbook_Master.docx",
    "SKILLS_DOC": "Transferable_Skills_to_Construction.docx",
    "RESUME_TEMPLATE": "resume_app_template.docx",
    "ROLE_ALIASES": "role_aliases.json",
    "SKILLS_JSON": "skills.json",
    "INSTRUCTOR_PACKET": "Instructor_Pathways_RankUp_Master.docx",  # optional, used for title/cover language if present
}

# ─────────────────────────────────────────────────────────
# Regex / constants
# ─────────────────────────────────────────────────────────
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(\+?1[\s\-\.]?)?\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4}")
PHONE_DIGITS = re.compile(r"\D+")
CITY_STATE_RE = re.compile(r"\b([A-Za-z .'-]{2,}),\s*([A-Za-z]{2})\b")
MULTISPACE = re.compile(r"\s+")
SECTION_HEADERS = re.compile(
    r"^(objective|summary|professional summary|skills|core competencies|experience|work history|employment|"
    r"education|certifications|certificates|references|contact|profile|qualifications|career|background|"
    r"achievements|accomplishments|projects|volunteer|activities|interests|technical skills|languages|"
    r"awards|honors|publications|training|licenses|memberships)$",
    re.I,
)

MAX_JOBS = 3
MAX_BULLETS_PER_JOB = 4
MAX_SKILLS = 12
MAX_SCHOOLS = 2
MAX_SUMMARY_CHARS = 450

# Cert normalization (labels must match exactly)
CERT_MAP = {
    "osha 10": "OSHA Outreach 10-Hour (Construction)",
    "osha-10": "OSHA Outreach 10-Hour (Construction)",
    "osha10": "OSHA Outreach 10-Hour (Construction)",
    "osha 30": "OSHA Outreach 30-Hour (Construction)",
    "osha-30": "OSHA Outreach 30-Hour (Construction)",
    "osha30": "OSHA Outreach 30-Hour (Construction)",
    "flagger": "WA Flagger (expires 3 years from issuance)",
    "wa flagger": "WA Flagger (expires 3 years from issuance)",
    "forklift": "Forklift — employer evaluation on hire",
    "fork lift": "Forklift — employer evaluation on hire",
    "cpr": "CPR",
    "first aid": "First Aid",
    "first-aid": "First Aid",
    "epa 608": "EPA Section 608 (Type I/II/III/Universal)",
    "epa section 608": "EPA Section 608 (Type I/II/III/Universal)",
}

# Trade taxonomy (headings must match playbook)
TRADE_TAXONOMY = [
    "Boilermaker", "Bricklayer / BAC Allied (Brick/Tile/Terrazzo/Marble/PCC)",
    "Carpenter (General)", "Carpenter – Interior Systems", "Millwright", "Pile Driver",
    "Cement Mason", "Drywall Finisher", "Electrician – Inside (01)", "Electrician – Limited Energy (06)",
    "Electrician – Residential (02)", "Elevator Constructor", "Floor Layer", "Glazier",
    "Heat & Frost Insulator", "Ironworker", "Laborer", "Operating Engineer", "Painter",
    "Plasterer", "Plumber / Steamfitter / HVAC-R", "Roofer", "Sheet Metal", "Sprinkler Fitter",
    "High Voltage – Outside Lineman", "Power Line Clearance Tree Trimmer",
]

# Bullet → skill hints (adds to skill buckets when user inserts a bullet)
BULLET_SKILL_HINTS = [
    (re.compile(r"\b(clean|organize|stage|restock|housekeep|walkway|sweep|debris)\b", re.I), "Attention to detail"),
    (re.compile(r"\b(pallet|forklift|lift|jack|rig|hoist|carry|load|unload|stack)\b", re.I), "Materials handling (wood/concrete/metal)"),
    (re.compile(r"\b(layout|measure|prints?|drawings?|blueprint)\b", re.I), "Reading blueprints & specs"),
    (re.compile(r"\b(grinder|drill|saw|snips|hand tools|power tools|torch)\b", re.I), "Hand & power tools"),
    (re.compile(r"\b(ppe|osha|lockout|tagout|loto|hazard|permit)\b", re.I), "Regulatory compliance"),
    (re.compile(r"\b(count|verify|inspect|qc|torque|measure)\b", re.I), "Critical thinking"),
    (re.compile(r"\b(rush|deadline|targets?|production|pace)\b", re.I), "Time management"),
    (re.compile(r"\b(team|crew|assist|support|communicat)\b", re.I), "Teamwork & collaboration"),
    (re.compile(r"\b(climb|lift|carry|physical|stamina)\b", re.I), "Physical stamina & dexterity"),
]

# ─────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────
def norm_ws(s: str) -> str:
    if not s: return ""
    return MULTISPACE.sub(" ", s.strip())

def clean_phone(s: str) -> str:
    if not s: return ""
    digits = PHONE_DIGITS.sub("", s)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return norm_ws(s)

def clean_bullet(s: str) -> str:
    if not s: return ""
    s = norm_ws(re.sub(r"^[•\-\u2022]+\s*", "", s))
    s = re.sub(r"\.+$", "", s)
    words = s.split()
    if len(words) > 24:
        s = " ".join(words[:24])
    return s[:1].upper() + s[1:] if s else s

def split_list(raw: str) -> List[str]:
    if not raw: return []
    parts = [p.strip(" •\t") for p in re.split(r"[,\n;•]+", raw)]
    return [p for p in parts if p]

# ─────────────────────────────────────────────────────────
# Extraction
# ─────────────────────────────────────────────────────────
def extract_text_from_pdf(upload) -> str:
    # Try pdfminer (text-based PDFs)
    try:
        if pdfminer_extract_text is not None:
            b = io.BytesIO(upload.getvalue()) if hasattr(upload, "getvalue") else io.BytesIO(upload.read())
            b.seek(0)
            txt = pdfminer_extract_text(b) or ""
            if txt.strip(): return txt
    except Exception:
        pass
    # Fallback: pypdf
    try:
        if hasattr(upload, "seek"):
            try: upload.seek(0)
            except Exception: pass
        reader = PdfReader(upload)
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""

def extract_text_from_docx(upload) -> str:
    try:
        doc = DocxReader(upload)
        parts = []
        for p in doc.paragraphs:
            t = p.text.strip()
            if t: parts.append(t)
        for tbl in doc.tables:
            for row in tbl.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    except Exception:
        return ""

def extract_text_generic(upload) -> str:
    name = getattr(upload, "name", "").lower()
    if name.endswith(".pdf"): return extract_text_from_pdf(upload)
    if name.endswith(".docx"): return extract_text_from_docx(upload)
    # TXT or unknown → try utf-8
    try:
        return upload.getvalue().decode("utf-8", errors="ignore")
    except Exception:
        try:
            return upload.read().decode("utf-8", errors="ignore")
        except Exception:
            return ""

# ─────────────────────────────────────────────────────────
# Header / education parsing
# ─────────────────────────────────────────────────────────
def _likely_name(lines: List[str]) -> str:
    best = ""
    best_score = -1.0
    for i, l in enumerate(lines[:20]):
        s = l.strip()
        if not s: continue
        if EMAIL_RE.search(s) or PHONE_RE.search(s): continue
        if SECTION_HEADERS.match(s): continue
        if re.search(r"(objective|summary|skills|experience|education|cert|resume|cv|curriculum)", s, re.I):
            continue
        words = [w for w in re.split(r"\s+", s) if w]
        if not (2 <= len(words) <= 4): continue
        if any(re.search(r"\d", w) for w in words): continue
        skip_words = {"address","phone","email","street","avenue","road","city","state","zip"}
        if any(w.lower() in skip_words for w in words): continue
        caps = sum(1 for w in words if w[:1].isalpha() and w[:1].isupper())
        score = caps / len(words) + (20 - i) * 0.01
        if score > best_score:
            best, best_score = s, score
    return best

def parse_header(text: str) -> Dict[str,str]:
    email = (EMAIL_RE.search(text or "") or [None]).group(0) if EMAIL_RE.search(text or "") else ""
    phone = (PHONE_RE.search(text or "") or [None]).group(0) if PHONE_RE.search(text or "") else ""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    mcs = CITY_STATE_RE.search("\n".join(lines[:30])) if lines else None
    city, state = (mcs.group(1), mcs.group(2).upper()) if mcs else ("","")
    name = _likely_name(lines)
    return {
        "Name": name,
        "Email": email.lower(),
        "Phone": clean_phone(phone),
        "City": city,
        "State": state
    }

def parse_education(text: str) -> List[Dict[str,str]]:
    out = []
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    EDU_KEY = re.compile(r"(high school|ged|college|university|program|certificate|diploma|academy|institute|school of)", re.I)
    YEAR = re.compile(r"\b(20\d{2}|19\d{2})\b")
    i = 0
    while i < len(lines) and len(out) < MAX_SCHOOLS:
        l = lines[i]
        if EDU_KEY.search(l):
            school = l
            cred, year, details = "", "", ""
            for la in lines[i+1:i+7]:
                if not year and YEAR.search(la): year = YEAR.search(la).group(0)
                if not details and CITY_STATE_RE.search(la):
                    m = CITY_STATE_RE.search(la); details = f"{m.group(1)}, {m.group(2).upper()}"
                if not cred and any(k in la.lower() for k in ["diploma","degree","certificate","ged","program","apprent","associate","bachelor","master"]):
                    cred = la.strip()
            out.append({"school": school, "credential": cred, "year": year, "details": details})
        i += 1
    return out[:MAX_SCHOOLS]

# ─────────────────────────────────────────────────────────
# Skills & certs
# ─────────────────────────────────────────────────────────
def load_json_safe(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

@st.cache_data
def load_skill_buckets() -> Dict[str, List[str]]:
    # Try skills.json first
    data = load_json_safe(SUPPORTING_DOCS["SKILLS_JSON"])
    if isinstance(data, dict) and all(k in data for k in ["Transferable","Job-Specific","Self-Management"]):
        return data
    # Fallback canon
    return {
        "Transferable": [
            "Problem-solving","Critical thinking","Attention to detail","Time management",
            "Teamwork & collaboration","Adaptability & willingness to learn","Customer service"
        ],
        "Job-Specific": [
            "Reading blueprints & specs","Hand & power tools","Operating machinery",
            "Materials handling (wood/concrete/metal)","Trades math & measurement","Regulatory compliance","Safety awareness"
        ],
        "Self-Management": [
            "Leadership","Physical stamina & dexterity","Reliability & punctuality"
        ]
    }

def parse_certs(text: str) -> List[str]:
    low = (text or "").lower()
    out = set()
    for k, v in CERT_MAP.items():
        if re.search(rf"\b{re.escape(k)}\b", low):
            out.add(v)
    return sorted(out)

def skills_from_bullets(bullets: List[str]) -> List[str]:
    hits = set()
    for b in bullets or []:
        for rx, skill in BULLET_SKILL_HINTS:
            if rx.search(b):
                hits.add(skill)
    return list(hits)

def suggest_transferable_from_text(text: str) -> List[str]:
    # Light keyword scan for initial seed
    KEY = {
        "problem":"Problem-solving","solve":"Problem-solving","troubleshoot":"Problem-solving",
        "analyz":"Critical thinking","detail":"Attention to detail","team":"Teamwork & collaboration",
        "collab":"Teamwork & collaboration","adapt":"Adaptability & willingness to learn",
        "learn":"Adaptability & willingness to learn","safety":"Safety awareness","blueprint":"Reading blueprints & specs",
        "forklift":"Operating machinery","material":"Materials handling (wood/concrete/metal)",
        "measure":"Trades math & measurement","code":"Regulatory compliance","permit":"Regulatory compliance",
        "lead":"Leadership","stamina":"Physical stamina & dexterity"
    }
    low = (text or "").lower()
    seen = []
    for k, lab in KEY.items():
        if k in low and lab not in seen:
            seen.append(lab)
    return seen[:6]

# ─────────────────────────────────────────────────────────
# Role detection & Job master
# ─────────────────────────────────────────────────────────
@st.cache_data
def load_role_aliases() -> Dict[str, List[str]]:
    data = load_json_safe(SUPPORTING_DOCS["ROLE_ALIASES"])
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if isinstance(v, list)}
    # Safe minimal fallback
    return {
        "Line Cook": ["line cook","cook","kitchen"],
        "Server": ["server","waiter","waitress"],
        "Warehouse Associate": ["warehouse associate","warehouse","whse"],
        "Janitor": ["janitor","custodian"],
        "Retail Associate": ["retail","sales associate"],
        "Barista": ["barista","coffee"],
        "Delivery Driver (Non-CDL)": ["delivery driver","driver","courier"],
    }

@st.cache_data
def read_job_master(path: str) -> Dict[str, List[str]]:
    roles: Dict[str, List[str]] = {}
    if not os.path.exists(path): return roles
    try:
        doc = DocxReader(path)
        cur = None
        for p in doc.paragraphs:
            style = (p.style.name or "").lower() if p.style else ""
            text = p.text.strip()
            if not text: continue
            if "heading 1" in style:
                cur = text
                roles.setdefault(cur, [])
                continue
            if cur:
                roles[cur].append(clean_bullet(text))
        # Dedup & clamp (keep 6–12)
        for k, v in roles.items():
            seen, dedup = set(), []
            for b in v:
                key = b.lower()
                if key in seen: continue
                seen.add(key); dedup.append(b)
            roles[k] = dedup[:12]
    except Exception:
        pass
    return roles

def detect_roles(text: str, aliases: Dict[str, List[str]]) -> List[str]:
    low = (text or "").lower()
    found = []
    for role, terms in aliases.items():
        pats = [re.compile(rf"\b{re.escape(t)}\b", re.I) for t in (terms if terms else [role.lower()])]
        if any(p.search(low) for p in pats):
            found.append(role)
    return found[:12]

# ─────────────────────────────────────────────────────────
# Playbook extraction for Instructor Packet
# ─────────────────────────────────────────────────────────
@st.cache_data
def read_playbook_sections(path: str) -> Dict[str, Tuple[int,int,List[str]]]:
    """
    Returns mapping: trade -> (start_idx, end_idx, paragraphs_text_list)
    We look for Heading 1 with exact trade name; end at next Heading 1.
    """
    out = {}
    if not os.path.exists(path): return out
    doc = DocxReader(path)
    # collect indices of Heading 1
    h1_indices = []
    for i, p in enumerate(doc.paragraphs):
        if p.style and "heading 1" in p.style.name.lower():
            h1_indices.append(i)
    # build ranges
    for idx, i in enumerate(h1_indices):
        title = doc.paragraphs[i].text.strip()
        j = h1_indices[idx+1] if idx+1 < len(h1_indices) else len(doc.paragraphs)
        paras = [doc.paragraphs[k].text for k in range(i, j)]
        out[title] = (i, j, paras)
    return out

def copy_trade_section_to(doc_out: DocxWriter, trade: str, sections: Dict[str, Tuple[int,int,List[str]]]):
    if trade not in sections:
        doc_out.add_paragraph(f"[Trade section not found: {trade}]")
        return
    _, _, paras = sections[trade]
    for t in paras:
        doc_out.add_paragraph(t)

# ─────────────────────────────────────────────────────────
# Objective starters
# ─────────────────────────────────────────────────────────
def objective_starters(trade: str) -> Tuple[List[str], List[str]]:
    # Neutral, measurable, crew-forward starters
    app = [
        f"Seeking an apprenticeship in {trade}; bring day-one value with safe pace, reliable attendance, and willingness to learn.",
        f"Ready to start {trade} apprenticeship; comfortable with PPE, jobsite etiquette, and following prints/layout under supervision.",
        f"Prepared for {trade} apprenticeship with shop/warehouse experience; track tasks, verify counts, and follow checklists.",
        f"Focused on building skills in {trade}; document measured work and seek feedback to improve on each rotation.",
        f"Motivated to learn {trade}; show up early, work safely around tools and materials, and support crew production goals.",
    ]
    job = [
        f"Looking for an entry-level {trade} role where I can contribute immediately at a safe pace and learn on the job.",
        f"Aim to support a {trade} crew with materials handling, cleanup, and accurate counts/measurements.",
        f"Bring dependable attendance, PPE habits, and careful tool control to a {trade} team.",
        f"Comfortable reading basic notes/prints and asking clarifying questions to keep work flowing in {trade}.",
        f"Ready for a helper/trainee role in {trade} with strong reliability and willingness to take direction.",
    ]
    return app, job

# ─────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────
@dataclass
class JobEntry:
    company: str = ""
    role: str = ""
    city: str = ""
    start: str = ""
    end: str = ""
    bullets: List[str] = None

    def trimmed(self) -> "JobEntry":
        bs = [clean_bullet(b) for b in (self.bullets or []) if str(b).strip()]
        return JobEntry(self.company, self.role, self.city, self.start, self.end, bs[:MAX_BULLETS_PER_JOB])

@dataclass
class SchoolEntry:
    school: str = ""
    credential: str = ""
    year: str = ""
    details: str = ""

# ─────────────────────────────────────────────────────────
# Session helpers
# ─────────────────────────────────────────────────────────
def ensure_state():
    st.session_state.setdefault("header", {"Name":"", "Phone":"", "Email":"", "City":"", "State":""})
    st.session_state.setdefault("trade_label", TRADE_TAXONOMY[0])
    st.session_state.setdefault("path", "Apprenticeship")
    st.session_state.setdefault("summary", "")
    st.session_state.setdefault("skills", {"Transferable":[], "Job-Specific":[], "Self-Management":[]})
    st.session_state.setdefault("certs", [])
    st.session_state.setdefault("jobs", [JobEntry().__dict__ for _ in range(MAX_JOBS)])
    st.session_state.setdefault("schools", [SchoolEntry().__dict__ for _ in range(MAX_SCHOOLS)])
    st.session_state.setdefault("role_to_add_target", 0)  # which job receives bullets

# ─────────────────────────────────────────────────────────
# UI Components
# ─────────────────────────────────────────────────────────
def sidebar_inputs() -> str:
    st.sidebar.header("Upload resumes / paste text")
    uploads = st.sidebar.file_uploader("Upload PDF / DOCX / TXT (you can add multiple)", type=["pdf","docx","txt"], accept_multiple_files=True)
    pasted = st.sidebar.text_area("Or paste resume text here", height=180, placeholder="Paste any resume/job text…")

    # Concatenate text from all sources
    texts = []
    for up in uploads or []:
        texts.append(extract_text_generic(up))
    if pasted.strip():
        texts.append(pasted.strip())
    text_all = "\n\n".join([t for t in texts if t and t.strip()])
    return text_all

def header_form(defaults: Dict[str,str]):
    c1, c2, c3, c4, c5 = st.columns([2,2,2,2,1.3])
    with c1: defaults["Name"] = st.text_input("Name", value=defaults.get("Name",""))
    with c2: defaults["Phone"] = st.text_input("Phone", value=defaults.get("Phone",""))
    with c3: defaults["Email"] = st.text_input("Email", value=defaults.get("Email",""))
    with c4:
        defaults["City"] = st.text_input("City", value=defaults.get("City",""))
        defaults["State"] = st.text_input("State (2-letter)", value=defaults.get("State",""))
    with c5:
        st.write("") ; st.write("")
        st.caption("Seattle tri-county (King / Pierce / Snohomish)")
    return defaults

def skills_editor(skills_buckets: Dict[str,List[str]]):
    st.subheader("Skills")
    canon = load_skill_buckets()
    # suggestion seed
    sugg = []
    for k in ["Transferable","Job-Specific","Self-Management"]:
        for s in skills_buckets.get(k, []):
            if s not in sugg: sugg.append(s)
    with st.expander("Suggested skills (click to add)", expanded=False):
        cols = st.columns(3)
        for i, s in enumerate((canon["Transferable"]+canon["Job-Specific"]+canon["Self-Management"])):
            if st.button(s, key=f"sug_{i}"):
                # insert into appropriate bucket (guess category from canon)
                bucket = "Transferable"
                if s in canon["Job-Specific"]: bucket = "Job-Specific"
                if s in canon["Self-Management"]: bucket = "Self-Management"
                cur = st.session_state["skills"].get(bucket, [])
                if s not in cur:
                    cur.append(s)
                    st.session_state["skills"][bucket] = cur

    c1, c2, c3 = st.columns(3)
    with c1:
        st.session_state["skills"]["Transferable"] = split_list(
            st.text_area("Transferable (comma/newline)", value=", ".join(st.session_state["skills"]["Transferable"]), height=120)
        )
    with c2:
        st.session_state["skills"]["Job-Specific"] = split_list(
            st.text_area("Job-Specific (comma/newline)", value=", ".join(st.session_state["skills"]["Job-Specific"]), height=120)
        )
    with c3:
        st.session_state["skills"]["Self-Management"] = split_list(
            st.text_area("Self-Management (comma/newline)", value=", ".join(st.session_state["skills"]["Self-Management"]), height=120)
        )

def certifications_editor(detected: List[str]):
    st.subheader("Certifications")
    if detected:
        st.caption("Detected:")
        st.write(", ".join(detected))
    cur = st.text_area("Add/confirm (comma/newline)", value=", ".join(st.session_state.get("certs", detected)), height=80)
    labs = [c.strip() for c in re.split(r"[,\n;]+", cur) if c.strip()]
    # normalize to exact labels
    out = set()
    for lab in labs:
        low = lab.lower()
        matched = None
        for k,v in CERT_MAP.items():
            if re.search(rf"\b{re.escape(k)}\b", low):
                matched = v; break
        out.add(matched or lab)
    st.session_state["certs"] = sorted(out)

def jobs_editor():
    st.subheader("Work Experience (up to 3)")
    for i in range(MAX_JOBS):
        j = st.session_state["jobs"][i]
        with st.container(border=True):
            st.markdown(f"**Job {i+1}**")
            c1, c2, c3, c4 = st.columns([2,2,2,2])
            j["company"] = c1.text_input("Company", key=f"company_{i}", value=j.get("company",""))
            j["role"] = c2.text_input("Title", key=f"role_{i}", value=j.get("role",""))
            j["city"] = c3.text_input("City, ST", key=f"city_{i}", value=j.get("city",""))
            j["start"] = c4.text_input("Start", key=f"start_{i}", value=j.get("start",""))
            j["end"] = c4.text_input("End", key=f"end_{i}", value=j.get("end",""))

            bullets = j.get("bullets", []) or []
            # Show existing bullets
            for bi, b in enumerate(bullets):
                bullets[bi] = st.text_input(f"•", key=f"b_{i}_{bi}", value=b)
            # Add bullet box
            new_b = st.text_input("Add bullet (trimmed to 24 words)", key=f"add_b_{i}", value="")
            if st.button("Add bullet", key=f"btn_add_b_{i}") and new_b.strip():
                bullets.append(clean_bullet(new_b))
                # infer skills from the single bullet
                gained = skills_from_bullets([new_b])
                for s in gained:
                    # Add to best guess bucket
                    bucket = "Transferable"
                    if s in load_skill_buckets()["Job-Specific"]: bucket = "Job-Specific"
                    if s in load_skill_buckets()["Self-Management"]: bucket = "Self-Management"
                    cur = st.session_state["skills"].get(bucket, [])
                    if s not in cur and sum(len(v) for v in st.session_state["skills"].values()) < MAX_SKILLS:
                        cur.append(s)
                        st.session_state["skills"][bucket] = cur
                st.rerun()
            j["bullets"] = bullets[:MAX_BULLETS_PER_JOB]
            st.session_state["jobs"][i] = j

def education_editor(detected_schools: List[Dict[str,str]]):
    st.subheader("Education (up to 2)")
    # seed
    if detected_schools:
        for i, e in enumerate(detected_schools[:MAX_SCHOOLS]):
            st.session_state["schools"][i].update(e)
    for i in range(MAX_SCHOOLS):
        e = st.session_state["schools"][i]
        with st.container(border=True):
            c1,c2 = st.columns([3,2])
            e["school"] = c1.text_input("School", key=f"sch_{i}", value=e.get("school",""))
            e["credential"] = c2.text_input("Credential", key=f"cred_{i}", value=e.get("credential",""))
            c3, c4 = st.columns([1,3])
            e["year"] = c3.text_input("Year", key=f"yr_{i}", value=e.get("year",""))
            e["details"] = c4.text_input("Details (City/State or notes)", key=f"det_{i}", value=e.get("details",""))
            st.session_state["schools"][i] = e

# ─────────────────────────────────────────────────────────
# Role bullet library panel
# ─────────────────────────────────────────────────────────
def role_library_panel(detected_roles: List[str], job_master: Dict[str, List[str]]):
    st.subheader("Detected / Available roles — click to insert duty bullets")
    if not job_master:
        st.info("Job_History_Master.docx not found or empty. You can still add bullets manually under each job.")
        return
    if not detected_roles:
        st.caption("No roles detected yet. You can still browse all roles below.")
    # Which job receives inserted bullets
    st.session_state["role_to_add_target"] = st.selectbox(
        "Insert bullets into:", options=[0,1,2], format_func=lambda i: f"Job {i+1}", index=st.session_state.get("role_to_add_target",0)
    )
    # Show detected first, then all roles
    show_list = detected_roles + [r for r in job_master.keys() if r not in detected_roles]
    for r in show_list:
        bullets = job_master.get(r, [])[:12]
        with st.expander(r, expanded=r in detected_roles):
            # Pick up to 6 alternates (multi-select)
            picks = st.multiselect("Choose bullets to insert", options=bullets, default=[], key=f"pick_{r}")
            if st.button(f"Insert into Job {st.session_state['role_to_add_target']+1}", key=f"ins_{r}"):
                tgt_idx = st.session_state["role_to_add_target"]
                tgt = st.session_state["jobs"][tgt_idx]
                cur_bullets = tgt.get("bullets", []) or []
                for b in picks:
                    if len(cur_bullets) >= MAX_BULLETS_PER_JOB: break
                    if b not in cur_bullets:
                        cur_bullets.append(clean_bullet(b))
                tgt["bullets"] = cur_bullets[:MAX_BULLETS_PER_JOB]
                st.session_state["jobs"][tgt_idx] = tgt
                # infer skills from selected bullets
                gained = skills_from_bullets(picks)
                for s in gained:
                    bucket = "Transferable"
                    canon = load_skill_buckets()
                    if s in canon["Job-Specific"]: bucket = "Job-Specific"
                    if s in canon["Self-Management"]: bucket = "Self-Management"
                    cur = st.session_state["skills"].get(bucket, [])
                    if s not in cur and sum(len(v) for v in st.session_state["skills"].values()) < MAX_SKILLS:
                        cur.append(s)
                        st.session_state["skills"][bucket] = cur
                st.rerun()

# ─────────────────────────────────────────────────────────
# Build outputs (Resume, Cover Letter, Instructor Packet)
# ─────────────────────────────────────────────────────────
def clamp_skills(sk: Dict[str,List[str]]) -> List[str]:
    # Flatten buckets preserving order and clamp to MAX_SKILLS
    out = []
    for k in ["Transferable","Job-Specific","Self-Management"]:
        for s in sk.get(k, []):
            if s not in out:
                out.append(s)
            if len(out) >= MAX_SKILLS: return out
    return out

def build_resume_context() -> Dict[str,Any]:
    header = st.session_state["header"]
    jobs = [JobEntry(**j).trimmed().__dict__ for j in st.session_state["jobs"]]
    schools = [SchoolEntry(**s).__dict__ for s in st.session_state["schools"]]
    skills_flat = clamp_skills(st.session_state["skills"])
    return {
        "Name": header.get("Name",""),
        "City": header.get("City",""),
        "State": header.get("State",""),
        "phone": header.get("Phone",""),
        "email": header.get("Email",""),
        "summary": st.session_state.get("summary",""),
        "skills": skills_flat,
        "certs": st.session_state.get("certs", []),
        "jobs": jobs,
        "schools": schools,
        "trade_label": st.session_state.get("trade_label",""),
    }

def render_docxtpl(template_path: str, context: Dict[str,Any]) -> bytes:
    tpl = DocxTemplate(template_path)
    tpl.render(context)
    bio = io.BytesIO()
    tpl.save(bio)
    bio.seek(0)
    return bio.read()

def build_cover_letter(context: Dict[str,Any]) -> bytes:
    doc = DocxWriter()
    # Simple, crew-forward letter using context
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.add_run(context["Name"]).bold = True
    doc.add_paragraph(f"{context['City']}, {context['State']} • {context['phone']} • {context['email']}")
    doc.add_paragraph("")  # spacer

    trade = context.get("trade_label","")
    path = st.session_state.get("path","Apprenticeship")
    body = []
    if path == "Apprenticeship":
        body.append(f"I’m applying for an apprenticeship in {trade}. I bring reliable attendance, safe PPE habits, and day-one usefulness supporting crew production.")
    else:
        body.append(f"I’m applying for an entry-level {trade} role. I can contribute immediately with safe pace, accurate counts, and good communication.")

    # Pull 3 bullets from jobs as highlights
    highlights = []
    for j in context["jobs"]:
        for b in j.get("bullets", [])[:1]:
            highlights.append(b)
        if len(highlights) >= 3: break
    if highlights:
        body.append("Highlights:")
        for h in highlights[:3]:
            doc.add_paragraph(f"• {h}")

    for line in body:
        if not line.startswith("•"):
            doc.add_paragraph(line)

    doc.add_paragraph("Thanks for your consideration.")
    doc.add_paragraph(context["Name"])
    b = io.BytesIO()
    doc.save(b); b.seek(0)
    return b.read()

def build_instructor_packet(reflection: str, uploads_text: str, chosen_trade: str) -> bytes:
    doc = DocxWriter()
    doc.add_heading("Instructor Pathway Packet", 0)
    doc.add_paragraph(f"Student: {st.session_state['header'].get('Name','')} — {datetime.now().strftime('%Y-%m-%d')}")
    doc.add_paragraph(f"Target: {st.session_state.get('path','')} — {chosen_trade}")
    doc.add_paragraph("")

    doc.add_heading("Workshop Reflections", level=1)
    doc.add_paragraph(reflection or "-")

    # Full text of uploads (lightly truncated per section)
    if uploads_text.strip():
        doc.add_heading("Uploaded Resume/Text (verbatim)", level=1)
        for chunk in textwrap.wrap(uploads_text, width=800):
            doc.add_paragraph(chunk)

    # Selected trade playbook section (verbatim)
    doc.add_heading(f"Stand-Out Playbook — {chosen_trade}", level=1)
    sections = read_playbook_sections(SUPPORTING_DOCS["PLAYBOOK"])
    copy_trade_section_to(doc, chosen_trade, sections)

    bio = io.BytesIO()
    doc.save(bio); bio.seek(0)
    return bio.read()

# ─────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────
def main():
    ensure_state()

    st.title("Construction Resume & Pathways — Seattle Tri-County")
    st.caption("Neutral language • Evidence over adjectives • Measurable bullets • No invented employers/dates")

    # Load supporting docs
    job_master = read_job_master(SUPPORTING_DOCS["JOB_MASTER"])
    role_alias = load_role_aliases()
    playbook_sections = read_playbook_sections(SUPPORTING_DOCS["PLAYBOOK"])

    # Sidebar: inputs
    raw_text = sidebar_inputs()

    # Autofill from text
    if raw_text:
        hdr = parse_header(raw_text)
        # Only fill if empty, never overwrite user's edits
        for k,v in hdr.items():
            if not st.session_state["header"].get(k):
                st.session_state["header"][k] = v
        # seed skills and certs
        seed_sk = suggest_transferable_from_text(raw_text)
        if seed_sk:
            cur = st.session_state["skills"]["Transferable"]
            for s in seed_sk:
                if s not in cur and sum(len(v) for v in st.session_state["skills"].values()) < MAX_SKILLS:
                    cur.append(s)
            st.session_state["skills"]["Transferable"] = cur
        detected_certs = parse_certs(raw_text)
    else:
        detected_certs = []

    # Header
    st.header("Header")
    st.session_state["header"] = header_form(st.session_state["header"])

    # Trade / Path / Objective
    st.subheader("Objective")
    c1, c2 = st.columns([2,2])
    with c1:
        st.session_state["trade_label"] = st.selectbox("Trade target", TRADE_TAXONOMY, index=TRADE_TAXONOMY.index(st.session_state.get("trade_label", TRADE_TAXONOMY[0])))
    with c2:
        st.session_state["path"] = st.radio("Path", ["Apprenticeship","Job"], index=0 if st.session_state.get("path","Apprenticeship")=="Apprenticeship" else 1, horizontal=True)

    app_opts, job_opts = objective_starters(st.session_state["trade_label"])
    with st.expander("Suggested objective starters (click to insert then edit)", expanded=False):
        cols = st.columns(5)
        picks = app_opts if st.session_state["path"]=="Apprenticeship" else job_opts
        for i, t in enumerate(picks):
            if cols[i%5].button(t, key=f"obj_{i}"):
                st.session_state["summary"] = t
                st.rerun()
    st.session_state["summary"] = st.text_area("Type your objective (1–2 sentences)", value=st.session_state.get("summary",""), height=90, max_chars=MAX_SUMMARY_CHARS)

    # Skills
    skills_editor(st.session_state["skills"])

    # Role detection + library
    detected = detect_roles(raw_text, role_alias) if raw_text else []
    role_library_panel(detected, job_master)

    # Jobs
    jobs_editor()

    # Certifications
    certifications_editor(detected_certs)

    # Education
    detected_schools = parse_education(raw_text) if raw_text else []
    education_editor(detected_schools)

    # Reflection for Instructor Packet
    st.subheader("Instructor Packet — Reflections (optional)")
    reflections = st.text_area("What did the student practice/learn? What proof do they have (logs, photos without faces, checklists)?", height=100)

    # Generate outputs
    st.header("Generate")
    ctx = build_resume_context()

    # Debug preview
    with st.expander("Autofill Debug — Parsed context (preview)"):
        st.json(ctx)
        st.caption(f"Detected roles: {', '.join(detected) or '-'}")
        st.caption(f"Playbook sections loaded: {len(playbook_sections)}")

    colA, colB, colC = st.columns(3)

    with colA:
        if os.path.exists(SUPPORTING_DOCS["RESUME_TEMPLATE"]):
            if st.button("Generate Resume (DOCX)"):
                docx_bytes = render_docxtpl(SUPPORTING_DOCS["RESUME_TEMPLATE"], ctx)
                st.download_button("Download Resume.docx", data=docx_bytes, file_name="Resume.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        else:
            st.error("Missing resume_app_template.docx in repo root.")

    with colB:
        if st.button("Generate Cover Letter (DOCX)"):
            letter_bytes = build_cover_letter(ctx)
            st.download_button("Download Cover_Letter.docx", data=letter_bytes, file_name="Cover_Letter.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    with colC:
        if st.button("Build Instructor Packet (DOCX)"):
            packet = build_instructor_packet(reflections, raw_text, st.session_state["trade_label"])
            st.download_button("Download Instructor_Packet.docx", data=packet, file_name="Instructor_Packet.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    st.caption("Guardrails: neutral language • evidence over adjectives • no invented employers/dates • bullets ≤ 24 words • total skills ≤ 12")


if __name__ == "__main__":
    main()
