"""Demo data: a Superadmin, one company with stacked roles, jobs, a question bank, a certification and candidates.

Run:  python seed.py          (adds demo data if the database is empty)
      python seed.py --reset  (drops every table first)
All demo passwords: Code2Hire@123
"""
import sys
from datetime import datetime, timedelta

from app import create_app
from extensions import db
from models import (Application, CandidateProfile, Certification, Company, HiringTemplate, Job, JobAssignment, Question,
                    QuestionFolder, QuestionVersion,
                    RoleAssignment, Team, User)
from services.perms import hash_password
from services.pipeline import invite_to_round, skill_match
from services.policy import install_defaults

PW = "Code2Hire@123"

Q = {
    "Python": [
        ("What does `list(map(lambda x: x * 2, [1, 2, 3]))` return?", ["[1, 2, 3, 1, 2, 3]", "[2, 4, 6]", "6", "A map object"], 1,
         "map applies the function to each item; list() materialises it."),
        ("Which data structure gives average O(1) membership tests?", ["list", "tuple", "set", "str"], 2, "Sets are hash-based."),
        ("What is the main effect of the GIL in CPython?",
         ["It stops all multithreading", "Only one thread runs Python bytecode at a time", "It speeds up I/O", "It prevents memory leaks"], 1,
         "Threads still help for I/O-bound work; CPU-bound work needs processes."),
        ("Why is `def f(items=[])` risky?", ["Lists can't be default values", "The default list is shared across calls",
                                             "It raises a SyntaxError", "It makes f a generator"], 1, "Defaults are evaluated once at definition time."),
        ("What does a `with` statement guarantee?", ["The block runs twice", "Cleanup via __exit__ even if an error is raised",
                                                    "The block is async", "Variables are local"], 1, "Context managers run __exit__ on any exit."),
        ("Which is a generator expression?", ["[x for x in r]", "{x for x in r}", "(x for x in r)", "{x: x for x in r}"], 2,
         "Parentheses create a lazy generator."),
        ("What does `@functools.lru_cache` do?", ["Logs calls", "Memoises results by arguments", "Runs in a thread", "Validates types"], 1,
         "It caches return values for repeated arguments."),
        ("Which is the safest way to build SQL with user input?", ["f-strings", "% formatting", "Parameterised queries", "str.replace quotes"], 2,
         "Parameters prevent SQL injection."),
    ],
    "React": [
        ("When does a `useEffect` with an empty dependency array run?", ["Every render", "Only after the first render (and cleanup on unmount)",
                                                                       "Never", "Before the first render"], 1, "Empty deps = mount/unmount."),
        ("Why do list items need a stable `key`?", ["For CSS", "So React can match items between renders", "For accessibility", "To sort them"], 1,
         "Keys identify items for reconciliation."),
        ("Calling `setCount(count + 1)` twice in one handler usually…", ["adds 2", "adds 1 because both read the same count",
                                                                        "throws", "re-renders twice and adds 2"], 1, "Use the updater form for sequential updates."),
        ("What does `useMemo` cache?", ["A component", "A computed value between renders", "Network responses", "State"], 1,
         "It recomputes only when dependencies change."),
        ("Where should data that several siblings need usually live?", ["In each sibling", "In their closest common parent",
                                                                       "In localStorage", "In a ref"], 1, "Lift state up."),
        ("What is a controlled input?", ["An input with a ref", "An input whose value comes from React state", "A disabled input",
                                         "An input inside a form"], 1, "React state is the single source of truth."),
    ],
    "JavaScript": [
        ("What is `typeof null`?", ["'null'", "'object'", "'undefined'", "'number'"], 1, "A long-standing quirk of the language."),
        ("Which declares a block-scoped variable that can be reassigned?", ["var", "let", "const", "function"], 1, "let is block-scoped and mutable."),
        ("What does `await` do inside an async function?", ["Blocks the whole thread", "Pauses that function until the promise settles",
                                                           "Creates a worker", "Nothing"], 1, "Other work continues on the event loop."),
        ("`[1, 2, 3].reduce((a, b) => a + b, 0)` returns", ["'123'", "6", "[1,2,3]", "0"], 1, "reduce folds the array into one value."),
        ("What does `===` check that `==` doesn't?", ["Value only", "Type and value without coercion", "Reference only", "Nothing"], 1,
         "Strict equality skips type coercion."),
        ("Which runs first?", ["setTimeout(fn, 0) callback", "A resolved promise's .then callback", "They run together", "Neither runs"], 1,
         "Microtasks run before the next macrotask."),
    ],
    "SQL": [
        ("Which clause filters groups after aggregation?", ["WHERE", "HAVING", "ORDER BY", "LIMIT"], 1, "HAVING filters aggregated groups."),
        ("A LEFT JOIN returns…", ["Only matching rows", "All rows from the left table, matched where possible", "All rows from both",
                                  "Only unmatched rows"], 1, "Unmatched right-side columns are NULL."),
        ("What does an index mainly speed up?", ["Inserts", "Lookups and filtering on the indexed columns", "Backups", "Schema changes"], 1,
         "Indexes trade write cost for read speed."),
        ("`COUNT(col)` vs `COUNT(*)`:", ["Identical", "COUNT(col) skips NULLs", "COUNT(*) skips NULLs", "COUNT(col) is always faster"], 1,
         "COUNT(col) counts non-null values."),
        ("Which isolation problem is a 'dirty read'?", ["Reading uncommitted changes from another transaction", "Reading stale cache",
                                                       "Reading deleted rows", "A slow query"], 0, "Prevented from READ COMMITTED upwards."),
        ("Window function to number rows per group:", ["GROUP_CONCAT", "ROW_NUMBER() OVER (PARTITION BY …)", "DISTINCT", "UNION"], 1,
         "PARTITION BY resets the numbering per group."),
    ],
    "Django": [
        ("What does `select_related` help avoid?", ["Migrations", "N+1 queries on foreign keys", "CSRF", "Template errors"], 1,
         "It joins related rows in one query."),
        ("Where do you change the database schema safely?", ["settings.py", "Migrations", "admin.py", "urls.py"], 1, "makemigrations + migrate."),
        ("What protects Django forms from cross-site request forgery?", ["CORS", "The CSRF token middleware", "Sessions", "HTTPS only"], 1,
         "{% csrf_token %} plus the middleware."),
        ("`QuerySet` evaluation is…", ["Immediate", "Lazy until iterated or sliced with a step", "Always cached forever", "Async"], 1,
         "Querysets hit the database when evaluated."),
    ],
    "AWS": [
        ("Which service is object storage?", ["EC2", "S3", "RDS", "Lambda"], 1, "S3 stores objects in buckets."),
        ("What is the least-privilege practice for IAM?", ["Use the root user", "Grant only the permissions a role needs",
                                                           "Share access keys", "Attach AdministratorAccess"], 1, "Scope policies narrowly."),
        ("A Lambda function is billed mainly by…", ["Instance hours", "Requests and execution time × memory", "Storage", "Bandwidth only"], 1,
         "Pay per invocation and duration."),
        ("Which spreads traffic across instances?", ["Route 53 only", "An Elastic Load Balancer", "CloudWatch", "S3"], 1,
         "ELB distributes requests."),
    ],
}

RESUMES = {
    "Arjun Mehta": ("Senior Python developer, 6 years", 6, "Senior Python developer with 6 years building Django and FastAPI services. "
                    "Led a payments platform migration to AWS (Lambda, S3, RDS) and cut p95 latency by 40%. Strong SQL and PostgreSQL, "
                    "Docker, Kubernetes basics, REST APIs, unit testing with pytest. Mentored 3 junior engineers."),
    "Meera Iyer": ("Frontend engineer, React and TypeScript", 4, "Frontend engineer, 4 years. React, TypeScript, JavaScript, Redux, "
                   "Next.js, CSS and accessibility. Built a design system used by 6 product teams. Some Node.js and GraphQL."),
    "Karan Shah": ("Backend developer", 2, "Backend developer with 2 years of Python and Django. Built internal tools and REST APIs with "
                   "MySQL. Learning AWS and Docker."),
    "Sana Khan": ("Data analyst moving into engineering", 3, "Data analyst, 3 years. SQL, Python (pandas), Excel, Power BI. Built "
                  "dashboards for sales operations. Interested in data engineering and Machine Learning."),
}


def run(reset=False):
    app = create_app()
    with app.app_context():
        if reset:
            db.drop_all()
            db.create_all()
        if User.query.filter_by(email="super@code2hire.ai").first():
            print("Demo data already present. Use --reset to start again.")
            return
        db.session.add(User(email="super@code2hire.ai", name="Platform Superadmin", kind="staff", is_superadmin=True,
                            password_hash=hash_password(PW)))
        # global bank, organised in folders, every question with its first version
        def folder(name, parent=None, company_id=None):
            f = QuestionFolder(company_id=company_id, name=name, parent_id=parent.id if parent else None)
            db.session.add(f)
            db.session.flush()
            return f
        eng = folder("Engineering")
        be, fe, cloud = folder("Backend", eng), folder("Frontend", eng), folder("Cloud and DevOps", eng)
        data = folder("Data")
        where = {"Python": folder("Python", be), "Django": folder("Django", be), "React": folder("React", fe),
                 "JavaScript": folder("JavaScript", fe), "SQL": folder("SQL", data), "AWS": folder("AWS", cloud)}
        tagmap = {"Python": ["core"], "Django": ["framework", "orm"], "React": ["hooks", "ui"], "JavaScript": ["core", "async"],
                  "SQL": ["queries"], "AWS": ["cloud"]}
        for skill, items in Q.items():
            for i, (text, opts, ans, why) in enumerate(items):
                q = Question(company_id=None, folder_id=where[skill].id, skill=skill, level=2 + (i % 3), text=text, options=opts, answer=ans,
                             explanation=why, status="approved", source="manual", version=1, tags=tagmap[skill])
                db.session.add(q)
                db.session.flush()
                db.session.add(QuestionVersion(question_id=q.id, version=1, snapshot=q.snapshot(), note="Created"))
        db.session.add(HiringTemplate(company_id=None, name="Standard tech hire", description="MCQ, AI interview, F2F with Isha, hiring manager",
                                      rounds=[{"type": "mcq", "name": "Skill screen", "config": {}},
                                              {"type": "ai_interview", "name": "AI interview with Hira", "config": {}},
                                              {"type": "f2f_isha", "name": "Technical F2F with Isha", "config": {}},
                                              {"type": "f2f_human", "name": "Hiring manager", "config": {}}]))
        db.session.add(Certification(company_id=None, name="Code2Hire Verified · Python Developer", skills=["Python"], level=3,
                                     issuer="Code2Hire", status="published",
                                     sections=[{"type": "mcq", "name": "Knowledge", "weight": 60, "questions": 8, "minutes": 15, "minimum": 50},
                                               {"type": "ai_interview", "name": "Spoken interview", "weight": 40, "questions": 3, "minutes": 15}],
                                     pass_rules={"cutoff": 60, "merit": 75, "distinction": 90}, proctoring="ai",
                                     attempts_allowed=2, cooldown_days=14, validity_months=24,
                                     output={"verification_page": True, "linkedin": True, "badge": True, "revoke_on_integrity": True}))

        c = Company(name="Acme Technologies", domain="acme.test", plan="employer", status="active", credits_total=5000,
                    limits={"seats": 25, "active_jobs": 25, "ai_minutes": 3000, "isha_hours": 60, "storage_days": 180},
                    flags={"public_jobs": True, "ai_interviews": True, "isha": True, "certifications": True},
                    branding={"color": "#5B3FFF"})
        db.session.add(c)
        db.session.flush()
        eng, data = Team(company_id=c.id, name="Engineering"), Team(company_id=c.id, name="Data")
        db.session.add_all([eng, data])
        db.session.flush()
        install_defaults(c.id)
        # Acme's own bank: folders and a question with real version history
        af = QuestionFolder(company_id=c.id, name="Senior Python screen", description="Used by the Engineering team")
        db.session.add(af)
        db.session.flush()
        af2 = QuestionFolder(company_id=c.id, name="Payments domain", parent_id=af.id)
        db.session.add(af2)
        db.session.flush()
        own = [("How do you make a payment callback safe to receive twice?", ["Ignore duplicates silently", "Use an idempotency key and a unique constraint",
                "Retry until it succeeds", "Lock the whole table"], 1, "Idempotency keys plus a unique constraint make retries safe.", af2.id, ["payments", "reliability"]),
               ("Which isolation level prevents dirty reads but allows non-repeatable reads?", ["Read uncommitted", "Read committed", "Repeatable read", "Serializable"], 1,
                "Read committed blocks dirty reads only.", af.id, ["databases"]),
               ("A Celery task must run exactly once per order. What's the safest design?", ["Rely on the broker", "Make the task idempotent and record completion",
                "Use a longer timeout", "Run it twice and compare"], 1, "Brokers deliver at least once; idempotency gives effectively-once.", af2.id, ["async", "payments"])]
        for i, (t, o, a_, e, fid, tags) in enumerate(own):
            q = Question(company_id=c.id, folder_id=fid, skill="Python", level=4, text=t, options=o, answer=a_, explanation=e,
                         status="approved", source="manual", version=1, tags=tags)
            db.session.add(q)
            db.session.flush()
            db.session.add(QuestionVersion(question_id=q.id, version=1, snapshot=q.snapshot(), note="Created"))
            if i == 0:  # show a real edit history
                q.text = "How do you make a payment-gateway callback safe to receive more than once?"
                q.version = 2
                db.session.add(QuestionVersion(question_id=q.id, version=2, snapshot=q.snapshot(), note="Clearer wording after candidate feedback"))

        def staff(email, name, roles, skills_meta=None):
            u = User(email=email, name=name, kind="staff", company_id=c.id, password_hash=hash_password(PW),
                     skills_meta=skills_meta or {}, last_login_at=datetime.utcnow())
            db.session.add(u)
            db.session.flush()
            for role, st, sid in roles:
                db.session.add(RoleAssignment(user_id=u.id, company_id=c.id, role=role, scope_type=st, scope_id=sid))
            return u

        staff("admin@acme.test", "Neha Kapoor", [("company_admin", "company", c.id)])
        priya = staff("priya@acme.test", "Priya Nair", [("manager", "company", c.id), ("interviewer", "company", c.id)],
                      {"skills": ["Python", "System design"]})
        rahul = staff("rahul@acme.test", "Rahul Verma", [("recruiter", "team", eng.id), ("interviewer", "team", eng.id)],
                      {"skills": ["React", "JavaScript"]})
        anita = staff("anita@acme.test", "Anita Desai", [("interviewer", "company", c.id)], {"skills": ["SQL", "Data"]})
        vikram = staff("vikram@acme.test", "Vikram Rao", [])

        def job(title, team, skills, status, vis, desc, rounds=None, smin=None, smax=None):
            j = Job(company_id=c.id, team_id=team.id, title=title, description=desc, skills=skills, level="Senior" if "Senior" in title else "Mid",
                    location="Bengaluru", work_mode="hybrid", salary_min=smin, salary_max=smax, salary_visible=bool(smax),
                    visibility=vis, status=status, created_by=rahul.id,
                    rounds=rounds or [{"type": "mcq", "name": "Skill screen", "config": {}},
                                      {"type": "ai_interview", "name": "AI interview with Hira", "config": {}},
                                      {"type": "f2f_isha", "name": "Technical F2F with Isha", "config": {}},
                                      {"type": "f2f_human", "name": "Hiring manager", "config": {}}],
                    rubric=[{"name": s["name"], "weight": 2 if s.get("must") else 1} for s in skills][:5],
                    plan={"questions": []}, deadline=(datetime.utcnow() + timedelta(days=30)).date(), hires_target=2)
            db.session.add(j)
            db.session.flush()
            db.session.add(JobAssignment(job_id=j.id, user_id=rahul.id, role="recruiter"))
            return j

        py = job("Senior Python Developer", eng, [{"name": "Python", "level": 4, "must": True}, {"name": "Django", "level": 3, "must": True},
                                                  {"name": "SQL", "level": 3, "must": True}, {"name": "AWS", "level": 2, "must": False}],
                 "live", "public", "Build and run the services behind our hiring products. You'll design APIs in Python and Django, "
                 "own data models in MySQL, and ship to AWS with the team.", smin=2400000, smax=3600000)
        fe = job("React Frontend Engineer", eng, [{"name": "React", "level": 3, "must": True}, {"name": "JavaScript", "level": 3, "must": True},
                                                  {"name": "TypeScript", "level": 2, "must": False}],
                 "live", "public", "Craft fast, accessible interfaces for recruiters and candidates with React and TypeScript.")
        job("Data Analyst", data, [{"name": "SQL", "level": 3, "must": True}, {"name": "Python", "level": 2, "must": False}],
            "draft", "private", "Turn hiring data into decisions.",
            rounds=[{"type": "mcq", "name": "SQL screen", "config": {}}, {"type": "f2f_human", "name": "Panel", "config": {}}])
        db.session.add(JobAssignment(job_id=py.id, user_id=vikram.id, role="hiring_manager"))
        db.session.add(JobAssignment(job_id=py.id, user_id=priya.id, role="interviewer"))
        db.session.add(JobAssignment(job_id=fe.id, user_id=anita.id, role="interviewer"))

        from services import ai
        cands = {}
        for name, (headline, yrs, resume) in RESUMES.items():
            email = name.split()[0].lower() + "@demo.test"
            u = User(email=email, name=name, kind="candidate", password_hash=hash_password(PW))
            db.session.add(u)
            db.session.flush()
            db.session.add(CandidateProfile(user_id=u.id, headline=headline, experience_years=yrs, location="Bengaluru",
                                            resume_text=resume, target_roles=["Senior Python Developer" if "Python" in resume else "Frontend Engineer"],
                                            skills=[{"name": s, "level": 3 if yrs >= 4 else 2, "verified": False, "source": "resume"}
                                                    for s in ai.extract_skills(resume)]))
            cands[name] = u
        db.session.flush()
        for name in ("Arjun Mehta", "Karan Shah", "Sana Khan"):
            p = CandidateProfile.query.filter_by(user_id=cands[name].id).first()
            s, got, missing = skill_match(py, p.skills)
            db.session.add(Application(job_id=py.id, candidate_id=cands[name].id, match_score=s, match_reasons={"matched": got, "missing": missing}))
        p = CandidateProfile.query.filter_by(user_id=cands["Meera Iyer"].id).first()
        s, got, missing = skill_match(fe, p.skills)
        db.session.add(Application(job_id=fe.id, candidate_id=cands["Meera Iyer"].id, match_score=s,
                                   match_reasons={"matched": got, "missing": missing}))
        db.session.flush()
        arjun_app = Application.query.filter_by(job_id=py.id, candidate_id=cands["Arjun Mehta"].id).first()
        invite_to_round(arjun_app, 0)
        meera_app = Application.query.filter_by(job_id=fe.id, candidate_id=cands["Meera Iyer"].id).first()
        invite_to_round(meera_app, 1)
        db.session.commit()
        print("Seeded. Sign in with any of these (password %s):" % PW)
        for e in ("super@code2hire.ai", "admin@acme.test", "priya@acme.test", "rahul@acme.test", "anita@acme.test",
                  "vikram@acme.test", "arjun@demo.test", "meera@demo.test"):
            print("  ", e)


if __name__ == "__main__":
    run(reset="--reset" in sys.argv)
