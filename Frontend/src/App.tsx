import { BrowserRouter, Routes, Route, Link, useLocation } from "react-router-dom";
import { Sprout, Leaf, FlaskConical } from "lucide-react";
import Dashboard from "./pages/Dashboard";
import CropHealth from "./pages/CropHealth";
import FertilizerAdvisor from "./pages/FertilizerAdvisor";

const links = [
  { to: "/", label: "Home", icon: Sprout },
  { to: "/crop-health", label: "Crop health", icon: Leaf },
  { to: "/fertilizer", label: "Fertilizer planner", icon: FlaskConical },
];

function Layout() {
  const { pathname } = useLocation();
  return (
    <div className="min-h-screen bg-[#f5f8f3] text-slate-800">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:font-semibold focus:text-green-900 focus:shadow">
        Skip to main content
      </a>
      <header className="border-b border-green-100 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-4">
          <Link to="/" className="flex items-center gap-2 text-xl font-bold text-green-900">
            <Sprout aria-hidden="true" />
            KrishiSaathi
          </Link>
          <nav className="flex flex-wrap gap-1" aria-label="Main">
            {links.map(({ to, label, icon: Icon }) => (
              <Link
                key={to}
                to={to}
                aria-current={pathname === to ? "page" : undefined}
                className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${
                  pathname === to ? "bg-green-100 text-green-900" : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                <Icon size={17} aria-hidden="true" />
                {label}
              </Link>
            ))}
          </nav>
        </div>
      </header>
      <main id="main-content" tabIndex={-1} className="mx-auto max-w-6xl px-5 py-8 outline-none">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/crop-health" element={<CropHealth />} />
          <Route path="/fertilizer" element={<FertilizerAdvisor />} />
          <Route
            path="*"
            element={
              <section className="py-16 text-center">
                <h1 className="text-3xl font-bold">Page not found</h1>
                <p className="mt-2 text-slate-600">
                  <Link className="font-semibold text-green-800 underline" to="/">
                    Go back home
                  </Link>
                </p>
              </section>
            }
          />
        </Routes>
      </main>
      <footer className="mt-12 border-t bg-white px-5 py-5 text-center text-xs leading-5 text-slate-600">
        KrishiSaathi is a portfolio project. Its results are decision aids, not professional advice: confirm with a local agriculture officer or Krishi Vigyan Kendra before treating a crop or buying fertiliser.
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Layout />
    </BrowserRouter>
  );
}
