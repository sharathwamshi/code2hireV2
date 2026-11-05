import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import Shell from "./components/Shell";
import { Loading } from "./components/ui";
import * as A from "./pages/admin/Admin";
import Analytics from "./pages/app/Analytics";
import Application from "./pages/app/Application";
import Approvals from "./pages/app/Approvals";
import { CertBuilder, CertsList } from "./pages/app/Certs";
import CompanyAdmin from "./pages/app/CompanyAdmin";
import Interviews from "./pages/app/Interviews";
import IshaRoom from "./pages/app/IshaRoom";
import { JobDetail, JobNew, JobsList } from "./pages/app/Jobs";
import Questions from "./pages/app/Questions";
import { ReportPage, ReportsList } from "./pages/app/Reports";
import Talent from "./pages/app/Talent";
import Today from "./pages/app/Today";
import * as M from "./pages/me/Me";
import { ChangePassword, Login, Signup } from "./pages/public/Auth";
import Landing from "./pages/public/Landing";
import Welcome from "./pages/public/Welcome";
import AddedCandidates from "./pages/app/AddedCandidates";
import { PublicJobs, SharedReport, Verify } from "./pages/public/Public";
import Room from "./pages/room/Room";
import { VERSION } from "./version";

function Guard({ kind, children, bare }) {
  const { me, ready } = useAuth();
  const loc = useLocation();
  if (!ready) return <Loading />;
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  if (kind === "super" && !me.user.is_superadmin) return <Navigate to={me.home} replace />;
  if (kind === "staff" && me.user.kind !== "staff" && !me.user.is_superadmin) return <Navigate to={me.home} replace />;
  if (kind === "candidate" && me.user.kind !== "candidate") return <Navigate to={me.home} replace />;
  return bare ? children : <Shell>{children}</Shell>;
}

/** The release number on every page (public pages, rooms, the app), small and out of the way. */
function VersionBadge() {
  const loc = useLocation();
  // the app shell (menu bar and footer) and the interview rooms show it themselves
  if (/^\/(app|admin|me|room)(\/|$)/.test(loc.pathname)) return null;
  return <div className="version-badge" aria-label={`Code2Hire version ${VERSION}`}>Code2Hire {VERSION}</div>;
}

export default function App() {
  const S = (el) => <Guard kind="staff">{el}</Guard>;
  const C = (el) => <Guard kind="candidate">{el}</Guard>;
  const SA = (el) => <Guard kind="super">{el}</Guard>;
  return (
    <>
    <VersionBadge />
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/password" element={<Guard bare><ChangePassword /></Guard>} />
      <Route path="/verify" element={<Verify />} />
      <Route path="/verify/:code" element={<Verify />} />
      <Route path="/shared/:token" element={<SharedReport />} />
      <Route path="/jobs" element={<PublicJobs />} />
      <Route path="/welcome/:token" element={<Welcome />} />

      <Route path="/admin" element={SA(<A.Overview />)} />
      <Route path="/admin/companies" element={SA(<A.Companies />)} />
      <Route path="/admin/companies/:id" element={SA(<A.CompanyDetail />)} />
      <Route path="/admin/settings" element={SA(<A.PlatformSettings />)} />
      <Route path="/admin/questions" element={SA(<A.GlobalQuestions />)} />
      <Route path="/admin/templates" element={SA(<A.Templates />)} />
      <Route path="/admin/certifications" element={SA(<A.CertReview />)} />
      <Route path="/admin/disputes" element={SA(<A.Disputes />)} />
      <Route path="/admin/users" element={SA(<A.Users />)} />
      <Route path="/admin/audit" element={SA(<A.Audit />)} />

      <Route path="/app" element={<Navigate to="/app/today" replace />} />
      <Route path="/app/today" element={S(<Today />)} />
      <Route path="/app/jobs" element={S(<JobsList />)} />
      <Route path="/app/jobs/new" element={S(<JobNew />)} />
      <Route path="/app/jobs/:id" element={S(<JobDetail />)} />
      <Route path="/app/applications/:id" element={S(<Application />)} />
      <Route path="/app/talent" element={S(<Talent />)} />
      <Route path="/app/candidates" element={S(<AddedCandidates />)} />
      <Route path="/app/interviews" element={S(<Interviews />)} />
      <Route path="/app/interviews/:id" element={<Guard kind="staff" bare><IshaRoom /></Guard>} />
      <Route path="/app/isha/:id" element={<Guard kind="staff" bare><IshaRoom /></Guard>} />
      <Route path="/app/reports" element={S(<ReportsList />)} />
      <Route path="/app/reports/:attemptId" element={S(<ReportPage />)} />
      <Route path="/app/analytics" element={S(<Analytics />)} />
      <Route path="/app/approvals" element={S(<Approvals />)} />
      <Route path="/app/certifications" element={S(<CertsList />)} />
      <Route path="/app/certifications/:id" element={S(<CertBuilder />)} />
      <Route path="/app/questions" element={S(<Questions />)} />
      <Route path="/app/admin" element={S(<CompanyAdmin />)} />
      <Route path="/app/audit" element={S(<CompanyAdmin initial="audit" />)} />

      <Route path="/me" element={C(<M.Home />)} />
      <Route path="/me/jobs" element={C(<M.Jobs />)} />
      <Route path="/me/jobs/:id" element={C(<M.JobView />)} />
      <Route path="/me/applications" element={C(<M.Applications />)} />
      <Route path="/me/practice" element={C(<M.Practice />)} />
      <Route path="/me/skills" element={C(<M.Skills />)} />
      <Route path="/me/badges" element={C(<M.Skills />)} />
      <Route path="/me/learning" element={C(<M.Learning />)} />
      <Route path="/me/certifications" element={C(<M.Certs />)} />
      <Route path="/me/feedback" element={C(<M.Feedback />)} />
      <Route path="/me/profile" element={C(<M.Profile />)} />

      <Route path="/room/:id" element={<Guard bare><Room /></Guard>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </>
  );
}
