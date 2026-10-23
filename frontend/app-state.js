// Shared in-memory state and presentation constants.
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

const BRAND_COLORS = {
  'Mizuno': ['#38BDF8', '#7DD3FC', '#0EA5E9'],
  'New Balance': ['#F87171', '#FCA5A5', '#EF4444'],
  'Adidas': ['#FACC15', '#FDE047', '#EAB308'],
  'PUMA': ['#4ADE80', '#86EFAC', '#22C55E'],
  'Nike': ['#FB923C', '#FDBA74', '#F97316'],
  'Asics': ['#A78BFA', '#C4B5FD', '#8B5CF6'],
  'Saucony': ['#F472B6', '#F9A8D4', '#EC4899'],
  'Hoka': ['#2DD4BF', '#5EEAD4', '#14B8A6'],
  'FILA': ['#FB7185', '#FDA4AF', '#F43F5E'],
  'On': ['#C084FC', '#D8B4FE', '#A855F7'],
  'Brooks': ['#34D399', '#6EE7B7', '#10B981'],
  'Skechers': ['#FBBF24', '#FDE68A', '#F59E0B'],
  'Under Armour': ['#94A3B8', '#CBD5E1', '#64748B'],
  'Salomon': ['#F97316', '#FDBA74', '#EA580C'],
};

const byDate = (a, b) => new Date(a.date) - new Date(b.date);
let shoes = [];
let retiredShoes = [];
let monthlyMileages = [];
let monthlySpending = [];
let spendingSummary = null;
let stravaImports = [];
let runningGoal = { version: 0, start_year: 2026, monthly_km: 125, yearly_km: 1500 };
let selectedYear = null;
let selectedGoalMonth = null;
let selectedSpendingYear = null;
let dashboardAnalyticsRequest = 0;
let reportLoadRequestId = 0;
let reportLoadController = null;
let reportGenerationRequestId = 0;
let reportGenerationController = null;
let currentTheme = localStorage.getItem('theme') || 'dark';

registerFeatureReset('dashboard-data', () => {
  shoes = []; retiredShoes = []; monthlyMileages = [];
  monthlySpending = []; spendingSummary = null;
  stravaImports = [];
  selectedYear = null; selectedGoalMonth = null; selectedSpendingYear = null;
  runningGoal = { version: 0, start_year: 2026, monthly_km: 125, yearly_km: 1500 };
});
