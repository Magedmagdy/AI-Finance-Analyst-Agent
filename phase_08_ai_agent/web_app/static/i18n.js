/* Bilingual dictionary (English / Arabic) + theme + language helpers.
   Loaded before app.js. Exposes window.I18N. */
(function () {
  const DICT = {
    en: {
      'brand.title': 'AI Finance',
      'brand.subtitle': 'Executive Copilot',
      'nav.newAnalysis': '＋ New analysis',
      'nav.workspace': 'Workspace',
      'nav.overview': '◉ Overview',
      'nav.trend': '⌁ Cash flow trend',
      'nav.drivers': '↗ Drivers',
      'nav.risk': '⚠ Risk & anomalies',
      'nav.forecast': '◎ Forecast',
      'side.boundary': 'Verified boundary',
      'side.actualConnected': 'Actual data connected',
      'side.engine': 'Engine',
      'side.provider': 'Provider',
      'side.model': 'Model',
      'side.turn': 'Turn',
      'side.viewLog': 'View execution log',
      'side.clear': 'Clear context',
      'side.unavailable': 'Unavailable',
      'top.eyebrow': 'FINANCIAL INTELLIGENCE · EXECUTIVE WORKSPACE',
      'top.title': 'See the numbers. Ask why. Act with context.',
      'top.subtitle': 'Verified analytics, deterministic calculations, and Gemini-powered financial narrative.',
      'top.live': 'Live analytical session',
      'top.refresh': 'Refresh dashboard',
      'pref.langTitle': 'Switch language',
      'pref.themeTitle': 'Switch theme',
      'pref.toLight': 'Light',
      'pref.toDark': 'Dark',
      'filter.currency': 'Currency',
      'filter.month': 'Analysis month',
      'filter.window': 'Trend window',
      'filter.m3': '3M', 'filter.m6': '6M', 'filter.m12': '12M',
      'filter.apply': 'Apply filters',
      'filter.latest': 'Latest actual period',
      'filter.current': 'Current: {month} · {currency}',
      'filter.refreshing': 'Refreshing verified dashboard…',
      'filter.failed': 'Refresh failed',
      'common.loading': 'Loading…',
      'hero.selected': 'SELECTED PERIOD',
      'hero.preparing': 'Preparing your executive dashboard from verified actual data.',
      'hero.desc': 'Executive view for the selected actual month, with {n} monthly observations in the trend window and verified next-month projection.',
      'hero.actualForecast': 'Actual + Forecast',
      'hero.execDash': 'Executive dashboard',
      'hero.verified': 'Verified data',
      'kpi.net': 'Net cash flow',
      'kpi.inflows': 'Total inflows',
      'kpi.outflows': 'Total outflows',
      'kpi.success': 'Transaction success',
      'kpi.fee': 'Fee rate',
      'kpi.forecast': 'Forecast next month',
      'kpi.inflowsMeta': 'Verified actual monetary inflows',
      'kpi.outflowsMeta': 'Verified actual monetary outflows',
      'kpi.successMeta': 'Completed / total transactions',
      'kpi.feeMeta': 'Fees / total outflows',
      'kpi.mom': '{pct} MoM',
      'kpi.noMom': 'No MoM comparison',
      'kpi.fcNA': 'Projection not available',
      'kpi.vsCurrent': 'Vs current: {delta}',
      'trend.title': 'Net cash flow trend',
      'trend.subtitle': 'Monthly verified actuals',
      'trend.months': '{n} months',
      'trend.none': 'No trend data available.',
      'trend.aria': 'Monthly net cash flow trend',
      'trend.low': 'Low: {v}',
      'trend.high': 'High: {v}',
      'health.title': 'Financial health signals',
      'health.subtitle': 'Observed indicators — no artificial score',
      'health.badge': 'Evidence-based',
      'health.position': 'Cash flow position',
      'health.negative': 'Negative',
      'health.positive': 'Positive',
      'health.netNote': 'Net cash flow: {v}',
      'health.ratio': 'Inflow / outflow',
      'health.ratioLow': 'Outflows are larger than inflows.',
      'health.ratioOk': 'Inflows are at least equal to outflows.',
      'health.success': 'Transaction success',
      'health.failedPending': 'Failed {f} · Pending {p}',
      'health.anomaly': 'Anomaly signal',
      'health.noneDetected': 'None detected',
      'health.detected': '{n} detected',
      'health.zNote': 'Modified Z-score threshold {t}',
      'drivers.title': 'Cash flow drivers',
      'drivers.subtitle': 'Current month vs previous month',
      'drivers.badge': 'Top contributors',
      'drivers.vs': '{a} vs {b}',
      'drivers.none': 'No driver data available for the selected period.',
      'drivers.contribution': '{p} contribution',
      'drivers.reconStatus': 'Driver reconciliation status: {s}.',
      'cmp.title': 'Month-over-month movement',
      'cmp.subtitle': 'Current selected month vs previous month',
      'cmp.none': 'No comparison available.',
      'cmp.net': 'Net cash flow',
      'cmp.abs': 'Absolute change',
      'cmp.pct': 'Percentage change',
      'risk.title': 'Risk & anomalies',
      'risk.subtitle': 'Modified Z-score · threshold 3.5',
      'risk.badge.one': '{n} anomaly',
      'risk.badge.many': '{n} anomalies',
      'risk.obs': 'Observations',
      'risk.anom': 'Anomalies',
      'risk.thr': 'Threshold',
      'risk.emptyTitle': 'No anomalies detected',
      'risk.emptyBody': 'Modified Z-score analysis returned no daily observations above the configured threshold for the selected month.',
      'risk.date': 'Date', 'risk.ccy': 'CCY', 'risk.observed': 'Observed', 'risk.z': 'Z-score', 'risk.dir': 'Direction',
      'fc.title': 'Forecast outlook',
      'fc.subtitle': 'Explicit projection from completed monthly history',
      'fc.badge': 'Forecast',
      'fc.none': 'No forecast available for this selection.',
      'fc.noHistory': 'No history available.',
      'fc.meta': '{method} · {n}-month lookback · Forecast, not actual.',
      'fc.higher': 'Less negative / higher than latest actual by {v}',
      'fc.lower': 'More negative / lower than latest actual by {v}',
      'chat.title': 'AI Finance Copilot',
      'chat.suggestions': 'Suggestions',
      'chat.placeholder': 'Ask about cash flow, trends, drivers, anomalies, ratios, forecasts, or ask “why?” to continue the current analysis…',
      'chat.send': 'Send',
      'chat.analyzing': 'Analyzing…',
      'chat.hint': 'Ctrl + Enter to send · Follow-ups preserve verified context · Dashboard filters are independent from chat context',
      'chat.empty': 'Ask a financial question to begin. The dashboard will populate from verified data while the Copilot keeps context for follow-ups.',
      'chat.mode': 'Context-aware conversation over verified financial data',
      'chat.langNote': 'The Copilot will answer in English.',
      'chat.bilingual': 'Bilingual AI',
      'sug.1': 'What was the biggest driver of the change?',
      'sug.2': 'What do the health indicators imply?',
      'sug.3': 'Were there any unusual days?',
      'sug.4': 'How does the forecast compare with the latest actual?',
      'log.title': 'Execution log',
      'log.subtitle': 'Tool routing, deterministic arguments, and validation trace',
      'log.empty': 'Run an analysis to capture the execution trace.',
      'toast.refreshed': 'Dashboard refreshed from verified data',
      'toast.refreshFail': 'Unable to refresh dashboard',
      'toast.done': 'Verified analysis complete',
      'toast.fail': 'Unable to complete analysis',
      'toast.cleared': 'Conversation context cleared',
      'toast.clearFail': 'Unable to clear context',
      'toast.loadFail': 'Unable to load dashboard session',
      'confirm.clear': 'Clear the current conversation context?',
      'toast.langEn': 'Language: English',
      'toast.langAr': 'Language: Arabic',
      'toast.themeDark': 'Dark mode on',
      'toast.themeLight': 'Light mode on',
      'val.positive': 'positive', 'val.negative': 'negative',
      'role.INFLOW': 'Inflow', 'role.OUTFLOW': 'Outflow', 'role.FEE': 'Fee', 'role.REFUND': 'Refund', 'role.OTHER': 'Other',
      'dir.increase': 'Increase', 'dir.decrease': 'Decrease', 'dir.unchanged': 'Unchanged', 'dir.up': 'Up', 'dir.down': 'Down', 'dir.flat': 'Flat',
      'dir.positive': 'Positive', 'dir.negative': 'Negative', 'dir.high': 'High', 'dir.low': 'Low',
      'recon.reconciled': 'reconciled',
      'mode.single_tool': 'single tool', 'mode.multi_tool': 'multi tool', 'mode.follow_up': 'follow up'
    },
    ar: {
      'brand.title': 'الذكاء المالي',
      'brand.subtitle': 'المساعد التنفيذي',
      'nav.newAnalysis': '＋ تحليل جديد',
      'nav.workspace': 'مساحة العمل',
      'nav.overview': '◉ نظرة عامة',
      'nav.trend': '⌁ اتجاه التدفق النقدي',
      'nav.drivers': '↗ المحركات',
      'nav.risk': '⚠ المخاطر والشذوذ',
      'nav.forecast': '◎ التوقعات',
      'side.boundary': 'نطاق البيانات الموثّق',
      'side.actualConnected': 'البيانات الفعلية متصلة',
      'side.engine': 'المحرّك',
      'side.provider': 'المزوّد',
      'side.model': 'النموذج',
      'side.turn': 'الدور',
      'side.viewLog': 'عرض سجل التنفيذ',
      'side.clear': 'مسح السياق',
      'side.unavailable': 'غير متاح',
      'top.eyebrow': 'الذكاء المالي · مساحة العمل التنفيذية',
      'top.title': 'الذكاء المالي · منصة التحليلات والقرارات الذكية',
      'top.subtitle': 'تحليلات موثّقة، وحسابات حتمية، وسرد مالي مدعوم بـ Gemini.',
      'top.live': 'جلسة تحليلية مباشرة',
      'top.refresh': 'تحديث لوحة المؤشرات',
      'pref.langTitle': 'تغيير اللغة',
      'pref.themeTitle': 'تغيير المظهر',
      'pref.toLight': 'فاتح',
      'pref.toDark': 'داكن',
      'filter.currency': 'العملة',
      'filter.month': 'شهر التحليل',
      'filter.window': 'نافذة الاتجاه',
      'filter.m3': '٣ أشهر', 'filter.m6': '٦ أشهر', 'filter.m12': '١٢ شهر',
      'filter.apply': 'تطبيق الفلاتر',
      'filter.latest': 'أحدث فترة فعلية',
      'filter.current': 'الحالي: {month} · {currency}',
      'filter.refreshing': 'جارٍ تحديث اللوحة الموثّقة…',
      'filter.failed': 'فشل التحديث',
      'common.loading': 'جارٍ التحميل…',
      'hero.selected': 'الفترة المختارة',
      'hero.preparing': 'جارٍ تجهيز لوحة المؤشرات التنفيذية من البيانات الفعلية الموثّقة.',
      'hero.desc': 'عرض تنفيذي للشهر الفعلي المختار، بعدد {n} ملاحظات شهرية في نافذة الاتجاه، مع توقع موثّق للشهر القادم.',
      'hero.actualForecast': 'فعلي + توقع',
      'hero.execDash': 'لوحة تنفيذية',
      'hero.verified': 'بيانات موثّقة',
      'kpi.net': 'صافي التدفق النقدي',
      'kpi.inflows': 'إجمالي التدفقات الداخلة',
      'kpi.outflows': 'إجمالي التدفقات الخارجة',
      'kpi.success': 'نجاح المعاملات',
      'kpi.fee': 'نسبة الرسوم',
      'kpi.forecast': 'توقع الشهر القادم',
      'kpi.inflowsMeta': 'التدفقات النقدية الداخلة الفعلية الموثّقة',
      'kpi.outflowsMeta': 'التدفقات النقدية الخارجة الفعلية الموثّقة',
      'kpi.successMeta': 'المعاملات المكتملة ÷ إجمالي المعاملات',
      'kpi.feeMeta': 'الرسوم ÷ إجمالي التدفقات الخارجة',
      'kpi.mom': '{pct} عن الشهر السابق',
      'kpi.noMom': 'لا توجد مقارنة شهرية',
      'kpi.fcNA': 'التوقع غير متاح',
      'kpi.vsCurrent': 'مقارنة بالحالي: {delta}',
      'trend.title': 'اتجاه صافي التدفق النقدي',
      'trend.subtitle': 'الأرقام الفعلية الشهرية الموثّقة',
      'trend.months': '{n} شهر',
      'trend.none': 'لا توجد بيانات اتجاه.',
      'trend.aria': 'اتجاه صافي التدفق النقدي الشهري',
      'trend.low': 'الأدنى: {v}',
      'trend.high': 'الأعلى: {v}',
      'health.title': 'مؤشرات الصحة المالية',
      'health.subtitle': 'مؤشرات مرصودة — بدون درجة اصطناعية',
      'health.badge': 'مبني على الأدلة',
      'health.position': 'وضع التدفق النقدي',
      'health.negative': 'سالب',
      'health.positive': 'موجب',
      'health.netNote': 'صافي التدفق النقدي: {v}',
      'health.ratio': 'الداخل ÷ الخارج',
      'health.ratioLow': 'التدفقات الخارجة أكبر من الداخلة.',
      'health.ratioOk': 'التدفقات الداخلة تساوي الخارجة على الأقل.',
      'health.success': 'نجاح المعاملات',
      'health.failedPending': 'فاشلة {f} · معلّقة {p}',
      'health.anomaly': 'إشارة الشذوذ',
      'health.noneDetected': 'لم يُرصد شيء',
      'health.detected': 'تم رصد {n}',
      'health.zNote': 'حد Z-score المعدّل {t}',
      'drivers.title': 'محركات التدفق النقدي',
      'drivers.subtitle': 'الشهر الحالي مقابل السابق',
      'drivers.badge': 'أكبر المساهمين',
      'drivers.vs': '{a} مقابل {b}',
      'drivers.none': 'لا توجد بيانات محركات للفترة المختارة.',
      'drivers.contribution': 'مساهمة {p}',
      'drivers.reconStatus': 'حالة مطابقة المحركات: {s}.',
      'cmp.title': 'الحركة من شهر لشهر',
      'cmp.subtitle': 'الشهر المختار مقابل الشهر السابق',
      'cmp.none': 'لا توجد مقارنة متاحة.',
      'cmp.net': 'صافي التدفق النقدي',
      'cmp.abs': 'التغيّر المطلق',
      'cmp.pct': 'نسبة التغيّر',
      'risk.title': 'المخاطر والشذوذ',
      'risk.subtitle': 'Z-score المعدّل · الحد 3.5',
      'risk.badge.one': '{n} شذوذ',
      'risk.badge.many': '{n} حالات شذوذ',
      'risk.obs': 'الملاحظات',
      'risk.anom': 'حالات الشذوذ',
      'risk.thr': 'الحد',
      'risk.emptyTitle': 'لم يُرصد أي شذوذ',
      'risk.emptyBody': 'تحليل Z-score المعدّل لم يجد أي ملاحظة يومية تتجاوز الحد المحدد في الشهر المختار.',
      'risk.date': 'التاريخ', 'risk.ccy': 'العملة', 'risk.observed': 'المرصود', 'risk.z': 'Z-score', 'risk.dir': 'الاتجاه',
      'fc.title': 'نظرة على التوقعات',
      'fc.subtitle': 'إسقاط صريح من التاريخ الشهري المكتمل',
      'fc.badge': 'توقع',
      'fc.none': 'لا يوجد توقع متاح لهذا الاختيار.',
      'fc.noHistory': 'لا يوجد تاريخ متاح.',
      'fc.meta': '{method} · فترة رجوع {n} أشهر · توقع وليس فعلي.',
      'fc.higher': 'أقل سلبية / أعلى من آخر فعلي بمقدار {v}',
      'fc.lower': 'أكثر سلبية / أقل من آخر فعلي بمقدار {v}',
      'chat.title': 'مساعد الذكاء المالي',
      'chat.suggestions': 'اقتراحات',
      'chat.placeholder': 'اسأل عن التدفق النقدي أو الاتجاهات أو المحركات أو الشذوذ أو النسب أو التوقعات، أو اسأل «ليه؟» لمتابعة التحليل الحالي…',
      'chat.send': 'إرسال',
      'chat.analyzing': 'جارٍ التحليل…',
      'chat.hint': 'Ctrl + Enter للإرسال · الأسئلة التالية تحافظ على السياق الموثّق · فلاتر اللوحة مستقلة عن سياق المحادثة',
      'chat.empty': 'اسأل سؤالًا ماليًا لتبدأ. هتتحدّث اللوحة من البيانات الموثّقة، والمساعد بيحتفظ بالسياق للأسئلة التالية.',
      'chat.mode': 'محادثة واعية بالسياق فوق بيانات مالية موثّقة',
      'chat.langNote': 'المساعد هيرد بالعربية.',
      'chat.bilingual': 'مساعد ثنائي اللغة',
      'sug.1': 'إيه أكبر محرّك للتغيّر؟',
      'sug.2': 'المؤشرات الصحية بتقول إيه؟',
      'sug.3': 'في أيام غير عادية؟',
      'sug.4': 'التوقع بيقارن إزاي بآخر رقم فعلي؟',
      'log.title': 'سجل التنفيذ',
      'log.subtitle': 'توجيه الأدوات والمعطيات الحتمية وأثر التحقق',
      'log.empty': 'شغّل تحليلًا لالتقاط سجل التنفيذ.',
      'toast.refreshed': 'تم تحديث اللوحة من البيانات الموثّقة',
      'toast.refreshFail': 'تعذّر تحديث اللوحة',
      'toast.done': 'اكتمل التحليل الموثّق',
      'toast.fail': 'تعذّر إكمال التحليل',
      'toast.cleared': 'تم مسح سياق المحادثة',
      'toast.clearFail': 'تعذّر مسح السياق',
      'toast.loadFail': 'تعذّر تحميل جلسة اللوحة',
      'confirm.clear': 'مسح سياق المحادثة الحالي؟',
      'toast.langEn': 'اللغة: الإنجليزية',
      'toast.langAr': 'اللغة: العربية',
      'toast.themeDark': 'تم تفعيل الوضع الداكن',
      'toast.themeLight': 'تم تفعيل الوضع الفاتح',
      'val.positive': 'موجب', 'val.negative': 'سالب',
      'role.INFLOW': 'داخل', 'role.OUTFLOW': 'خارج', 'role.FEE': 'رسوم', 'role.REFUND': 'استرداد', 'role.OTHER': 'أخرى',
      'dir.increase': 'زيادة', 'dir.decrease': 'انخفاض', 'dir.unchanged': 'دون تغيّر', 'dir.up': 'ارتفاع', 'dir.down': 'هبوط', 'dir.flat': 'ثابت',
      'dir.positive': 'موجب', 'dir.negative': 'سالب', 'dir.high': 'مرتفع', 'dir.low': 'منخفض',
      'recon.reconciled': 'مطابَق',
      'mode.single_tool': 'أداة واحدة', 'mode.multi_tool': 'عدة أدوات', 'mode.follow_up': 'متابعة'
    }
  };

  // Arabic names for common transaction types coming from the data layer.
  // Unknown values are shown as-is (they are data, not UI text).
  const TXN_AR = {
    deposit: 'إيداع', withdrawal: 'سحب', transfer: 'تحويل', payment: 'دفع', refund: 'استرداد',
    fee: 'رسوم', purchase: 'شراء', cashout: 'سحب نقدي', cash_in: 'إيداع نقدي', cash_out: 'سحب نقدي',
    top_up: 'شحن رصيد', topup: 'شحن رصيد', bill_payment: 'سداد فواتير', salary: 'مرتب', interest: 'فوائد',
    other: 'أخرى'
  };

  const state = {
    lang: 'en',
    theme: 'dark'
  };

  function safeGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function safeSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  function t(key, vars) {
    const table = DICT[state.lang] || DICT.en;
    let s = table[key];
    if (s === undefined) s = DICT.en[key];
    if (s === undefined) return key;
    if (vars) {
      for (const k of Object.keys(vars)) s = s.split('{' + k + '}').join(String(vars[k]));
    }
    return s;
  }

  function locale() { return state.lang === 'ar' ? 'ar-EG-u-nu-latn' : 'en-US'; }

  function translateTxn(name) {
    if (state.lang !== 'ar') return name;
    const key = String(name || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    return TXN_AR[key] || name;
  }

  function applyStatic() {
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.setAttribute('placeholder', t(el.dataset.i18nPlaceholder)); });
    document.querySelectorAll('[data-i18n-title]').forEach(el => { el.setAttribute('title', t(el.dataset.i18nTitle)); });
    // The send button holds a label span + arrow, handled by data-i18n on the inner span.
    const langLabel = document.getElementById('langBtnLabel');
    if (langLabel) langLabel.textContent = state.lang === 'ar' ? 'English' : 'العربية';
    const themeLabel = document.getElementById('themeBtnLabel');
    const themeIcon = document.getElementById('themeIcon');
    if (themeLabel) themeLabel.textContent = state.theme === 'dark' ? t('pref.toLight') : t('pref.toDark');
    if (themeIcon) themeIcon.textContent = state.theme === 'dark' ? '☀' : '☾';
    document.title = state.lang === 'ar' ? 'محلل مالي بالذكاء الاصطناعي — لوحة تنفيذية' : 'AI Finance Analyst — Executive Dashboard';
  }

  function setLang(lang) {
    state.lang = lang === 'ar' ? 'ar' : 'en';
    const root = document.documentElement;
    root.setAttribute('lang', state.lang);
    root.setAttribute('dir', state.lang === 'ar' ? 'rtl' : 'ltr');
    safeSet('af_lang', state.lang);
    applyStatic();
  }

  function setTheme(theme) {
    state.theme = theme === 'light' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', state.theme);
    safeSet('af_theme', state.theme);
    applyStatic();
  }

  function init() {
    state.lang = safeGet('af_lang') === 'ar' ? 'ar' : 'en';
    const savedTheme = safeGet('af_theme');
    state.theme = savedTheme || (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    document.documentElement.setAttribute('lang', state.lang);
    document.documentElement.setAttribute('dir', state.lang === 'ar' ? 'rtl' : 'ltr');
    document.documentElement.setAttribute('data-theme', state.theme);
  }
  init();

  window.I18N = {
    state, t, locale, setLang, setTheme, applyStatic, translateTxn,
    get lang() { return state.lang; },
    get theme() { return state.theme; }
  };
})();
