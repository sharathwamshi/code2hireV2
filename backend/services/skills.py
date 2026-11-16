"""Skill names, matching and role skills (V02.00.10).

One place for:
  - canon(name): how a skill or role is written ("sap attp" -> "SAP ATTP", "power bi" -> "Power BI"), LRN-02;
  - options(name): the alternatives inside one job requirement ("JavaScript / TypeScript" -> JavaScript, TypeScript;
    "Modern frontend framework (React, Angular or Vue)" -> React, Angular, Vue), JOB-07;
  - same(a, b): two names for one skill (JS = JavaScript, ReactJS = React, k8s = Kubernetes);
  - extract(text): skills named in a resume, by whole word (so "JavaScript" no longer also counts as "Java"), CP-004;
  - role_skills(role): the skills a role needs, from live jobs with a similar title, then Claude, then the dictionary,
    CP-011.
"""
import re

KNOWN = ["Java", "Spring Boot", "SQL", "Python", "Django", "Flask", "FastAPI", "React", "JavaScript", "TypeScript",
         "Node.js", "Express", "Kubernetes", "Docker", "AWS", "Azure", "GCP", "Kafka", "Microservices", "System design",
         "Data analysis", "Data analytics", "Excel", "Power BI", "Tableau", "Statistics", "Machine learning", "Deep learning",
         "NLP", "Communication", "Sales", "Negotiation", "CRM", "Customer success", "Go", "C#", ".NET", "C++", "Angular", "Vue",
         "DevOps", "Linux", "Testing", "Manual testing", "Automation testing", "Selenium", "Cypress", "Playwright",
         "Product management", "Figma", "PostgreSQL", "MySQL", "MongoDB", "Redis", "HTML", "CSS", "Git", "CI/CD",
         "Jenkins", "Terraform", "REST APIs", "GraphQL", "Spark", "Hadoop", "Airflow", "Snowflake", "Pandas", "NumPy",
         "SAP", "SAP ATTP", "SAP S/4HANA", "Salesforce", "Agile", "Scrum", "Jira", "Problem solving", "Leadership"]

# words that are always written in capitals, and words with a fixed spelling
ACRONYMS = {"sap", "attp", "sql", "aws", "gcp", "api", "apis", "ui", "ux", "qa", "hr", "crm", "erp", "seo", "nlp", "ml",
            "ai", "bi", "etl", "css", "html", "json", "xml", "rest", "sdk", "ios", "it", "kpi", "mis", "devops_", "ci", "cd",
            "vapt", "soc", "iam", "jvm", "oop", "dsa", "tcp", "ip", "dns", "http", "https", "uat", "sla", "b2b", "b2c", "saas",
            "s/4hana", "abap", "fico", "mm", "sd", "pp", "hcm", "bw", "gst", "llm", "rag", "gpu", "cpu", "php", "net"}
FIXED = {k.lower(): k for k in KNOWN}
FIXED.update({"javascript": "JavaScript", "typescript": "TypeScript", "node.js": "Node.js", "nodejs": "Node.js", "node": "Node.js",
              "postgresql": "PostgreSQL", "mysql": "MySQL", "mongodb": "MongoDB", "graphql": "GraphQL", "devops": "DevOps",
              "github": "GitHub", "gitlab": "GitLab", "numpy": "NumPy", "pytorch": "PyTorch", "tensorflow": "TensorFlow",
              ".net": ".NET", "c#": "C#", "c++": "C++", "ios": "iOS", "fastapi": "FastAPI", "power bi": "Power BI",
              "s/4hana": "S/4HANA", "sap s/4hana": "SAP S/4HANA", "ci/cd": "CI/CD", "rest apis": "REST APIs"})
SMALL = {"and", "or", "of", "in", "for", "to", "with", "on", "the", "a", "an", "at", "by"}

SYNONYMS = {"js": "javascript", "ts": "typescript", "reactjs": "react", "react.js": "react", "react js": "react",
            "nodejs": "node.js", "node": "node.js", "postgres": "postgresql", "k8s": "kubernetes", "golang": "go",
            "ml": "machine learning", "dl": "deep learning", "springboot": "spring boot", "spring": "spring boot",
            "amazon web services": "aws", "ms excel": "excel", "microsoft excel": "excel", "powerbi": "power bi",
            "vuejs": "vue", "vue.js": "vue", "angularjs": "angular", "rest": "rest apis", "rest api": "rest apis",
            "manual qa": "manual testing", "qa": "testing", "software testing": "testing", "sap-attp": "sap attp",
            "data analysis": "data analytics", "analytics": "data analytics"}


def canon(name):
    """How a skill or role name is written: acronyms in capitals, fixed spellings, other words capitalised."""
    s = re.sub(r"\s+", " ", str(name or "")).strip()
    if not s:
        return s
    if s.lower() in FIXED:
        return FIXED[s.lower()]
    out = []
    for i, w in enumerate(s.split(" ")):
        lw = w.lower()
        core = lw.strip("(),.:;")
        if lw in FIXED:
            out.append(FIXED[lw])
        elif core in ACRONYMS:
            out.append(w.upper())
        elif i and lw in SMALL:
            out.append(lw)
        elif w[:1].islower() or w.isupper() and len(w) > 4:
            out.append(w[:1].upper() + w[1:].lower() if w.isupper() else w[:1].upper() + w[1:])
        else:
            out.append(w)
    return " ".join(out)


def _key(name):
    k = re.sub(r"\s+", " ", str(name or "").lower()).strip(" .")
    return SYNONYMS.get(k, k)


def same(a, b):
    return bool(a and b) and _key(a) == _key(b)


def options(name):
    """The alternatives inside one requirement. "JavaScript / TypeScript" -> [JavaScript, TypeScript];
    "Modern frontend framework (React, Angular or Vue)" -> [React, Angular, Vue]; "Python" -> [Python]."""
    s = str(name or "").strip()
    inner = re.search(r"\(([^)]*)\)", s)
    parts = []
    if inner and re.search(r",|\bor\b|/", inner.group(1)):
        parts = re.split(r"\s*(?:,|/|\bor\b|\|)\s*", inner.group(1))
    elif not re.search(r"\b(?:s/4hana|ci/cd|tcp/ip)\b", s, re.I):
        parts = re.split(r"\s*(?:/|\||\bor\b)\s*", s) if re.search(r"/|\||\bor\b", s) else []
    parts = [p.strip(" .") for p in parts if p and p.strip(" .")]
    return parts or [s]


def find(need, have):
    """The profile skill (dict) that satisfies one job requirement, or None."""
    for opt in options(need):
        for h in have:
            if same(opt, h.get("name")):
                return h
    return None


def extract(text):
    """Known skills named in the text, as whole words, in canonical spelling."""
    t = " " + (text or "").lower() + " "
    found = []
    names = set(KNOWN) | {FIXED[k] for k in ("node.js", "github", "pytorch", "tensorflow")}
    for s in sorted(names, key=len, reverse=True):
        pat = r"(?<![a-z0-9+#.])" + re.escape(s.lower()) + r"(?![a-z0-9+#])"
        if re.search(pat, t) and not any(same(s, f) for f in found):
            found.append(s)
    for syn, real in SYNONYMS.items():
        if len(syn) > 2 and re.search(r"(?<![a-z0-9])" + re.escape(syn) + r"(?![a-z0-9])", t):
            name = canon(real)
            if not any(same(name, f) for f in found):
                found.append(name)
    # "SAP" only because "SAP ATTP" was named: keep the longer one
    return [f for f in found if not any(o != f and re.search(r"(?<![a-z0-9])" + re.escape(f.lower()) + r"(?![a-z0-9])", o.lower()) for o in found)]


def role_skills(role, profile_skills=(), n=5):
    """Skills a role needs: live jobs with a similar title first, then Claude, then the role's own words."""
    from models import Job
    words = {w for w in re.findall(r"[a-z0-9+#.]+", (role or "").lower()) if len(w) > 2 and w not in ("senior", "junior", "lead", "developer", "engineer")}
    counts = {}
    if words:
        for j in Job.query.filter(Job.status.in_(("live", "closed"))).limit(400).all():
            tw = set(re.findall(r"[a-z0-9+#.]+", (j.title or "").lower()))
            if words & tw:
                for s in j.skills or []:
                    nm = s["name"] if isinstance(s, dict) else s
                    for o in options(nm):
                        counts[canon(o)] = counts.get(canon(o), 0) + 1
    picked = [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:n]
    if len(picked) < 3:
        from services import ai
        if ai.configured():
            out = ai.ask_json("list the core skills for a role", f"""Role: {role}
List the {n} most important, specific technical or professional skills a hiring interviewer would test for this role.
Return JSON: {{"skills": [str]}} (short names like "SQL", "Power BI", "SAP ATTP configuration").""",
                              lambda: {"skills": []}, max_tokens=200, timeout=10)
            for s in (out or {}).get("skills") or []:
                if not any(same(s, p) for p in picked):
                    picked.append(canon(s))
    if len(picked) < 3:
        for s in extract(role):
            if not any(same(s, p) for p in picked):
                picked.append(s)
    if len(picked) < 3:  # last resort: profile skills that appear in the role's words
        for s in profile_skills or []:
            nm = s.get("name") if isinstance(s, dict) else s
            if nm and _key(nm) in words and not any(same(nm, p) for p in picked):
                picked.append(canon(nm))
    return picked[:n] or [canon(role)]


LEVELS = {1: ("Beginner", "Knows the basics and the words."), 2: ("Working", "Can build features with some guidance."),
          3: ("Independent", "Works without help on everyday tasks."), 4: ("Advanced", "Designs solutions and reviews others' work."),
          5: ("Expert", "Leads, teaches and solves the hardest problems.")}
