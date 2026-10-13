import { Link } from "react-router-dom";
import { ArrowRight, Calculator, Camera, ScanSearch, ShieldCheck } from "lucide-react";

const modules = [
  {
    to: "/crop-health",
    title: "Crop health",
    desc: "Photograph a leaf and get a screening result for 38 disease and healthy classes across 14 crops. A heat-map shows what the model looked at, and the page shows how it performed on real field photos.",
    cta: "Check a leaf",
    icon: Camera,
  },
  {
    to: "/fertilizer",
    title: "Fertilizer planner",
    desc: "Turn the nutrient dose on your Soil Health Card into a plan: which products, how many kilograms for your acres or gunthas, and how to split them. Every number is traceable to a source.",
    cta: "Plan fertilizer",
    icon: Calculator,
  },
];

const principles = [
  { icon: ScanSearch, title: "Tested, not assumed", text: "The leaf model is evaluated on photos taken in real fields, and the results are published, including where it fails." },
  { icon: ShieldCheck, title: "Never invents numbers", text: "Doses come from your own report or a cited source. The planner does arithmetic; it does not guess what your crop needs." },
];

export default function Dashboard() {
  return (
    <div>
      <section className="mb-8 rounded-3xl bg-gradient-to-r from-green-900 to-green-700 px-7 py-10 text-white">
        <p className="mb-2 text-sm font-semibold uppercase tracking-widest text-green-100">Two practical tools, honest about their limits</p>
        <h1 className="text-3xl font-bold md:text-4xl">Smarter decisions on the farm</h1>
        <p className="mt-3 max-w-2xl text-green-50">Check a leaf for common diseases, then turn your soil-test dose into a clear fertiliser plan.</p>
      </section>
      <ul className="grid gap-5 md:grid-cols-2">
        {modules.map(({ to, title, desc, cta, icon: Icon }) => (
          <li key={to}>
            <Link to={to} className="group flex h-full flex-col rounded-2xl border border-green-100 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md motion-reduce:transition-none motion-reduce:hover:translate-y-0">
              <div className="mb-4 inline-flex w-fit rounded-xl bg-green-50 p-3 text-green-800">
                <Icon aria-hidden="true" />
              </div>
              <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-700">{desc}</p>
              <span className="mt-auto inline-flex items-center gap-2 pt-5 text-sm font-semibold text-green-800">
                {cta} <ArrowRight size={16} aria-hidden="true" className="transition group-hover:translate-x-1 motion-reduce:transition-none" />
              </span>
            </Link>
          </li>
        ))}
      </ul>
      <ul className="mt-6 grid gap-4 md:grid-cols-2">
        {principles.map(({ icon: Icon, title, text }) => (
          <li key={title} className="flex gap-3 rounded-xl border bg-white p-4">
            <Icon aria-hidden="true" className="mt-0.5 shrink-0 text-green-800" size={20} />
            <div>
              <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-700">{text}</p>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-8 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
        Crop disease results are a screening aid for apple, blueberry, cherry, corn, grape, orange, peach, bell pepper, potato, raspberry, soybean, squash, strawberry and tomato leaves. Always confirm with a local agriculture officer before treating a crop.
      </p>
    </div>
  );
}
