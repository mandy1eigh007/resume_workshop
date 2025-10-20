Seattle Tri-County Construction Resume & Pathways App

Single-file Streamlit app that:

Parses uploaded resumes (PDF/DOCX/TXT/URLs) and autofills fields.

Detects roles and maps them to duty bullets from Job_History_Master.docx; inserting a bullet also adds aligned skills (Transferable / Job-Specific / Self-Management).

Normalizes certifications (OSHA-10/30, WA Flagger, Forklift employer eval, CPR/First Aid, EPA 608).

Generates a docxtpl resume using resume_app_template.docx.

Builds an Instructor Pathway Packet that embeds student reflections + the correct trade section from Stand_Out_Playbook_Master.docx.

Uses only GitHub + Streamlit Cloud. No local Python needed.
