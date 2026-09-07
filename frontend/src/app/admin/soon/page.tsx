"use client";

import { AppShell, RequireAuth } from "@/components/shell";
import { Panel } from "@/components/ui";

/** Phase two is announced, not built. No logic lives behind this screen. */
const ITEMS = [
  {
    title: "تكاملات المنصّات الاجتماعية",
    body: "النشر المباشر لمخرجات المقاسات الرقمية إلى حسابات العميل، مع قوالب مقاسات جاهزة لكل منصّة ومكتبة نصوص إعلانية.",
    points: [
      "مقاسات رقمية مشتقّة من قالب الطبع نفسه",
      "جدولة نشر مرتبطة بتاريخ العرض في ملف Excel",
    ],
  },
  {
    title: "اختيار المستقلّين",
    body: "سوق مصغّر داخل المنصّة: يطلب العميل تصميم قالب جديد، فيُعرض الطلب على مصمّمين مستقلّين معتمدين، ويصل التصميم إلى محرّر القوالب مباشرة.",
    points: [
      "ملفّ مستقل بأعماله وتقييمه",
      "تسليم يخضع لفحص جاهزية الطبع تلقائيًا",
    ],
  },
];

export default function SoonPage() {
  return (
    <RequireAuth staffOnly>
      <AppShell breadcrumb="لوحة المشرف / المرحلة الثانية">
        <h1 className="text-2xl font-semibold">قريبًا</h1>
        <p className="mt-3 max-w-2xl text-md leading-relaxed text-muted">
          هذان البندان مذكوران في المنصّة الآن كإعلان نيّة فقط، بلا واجهات عمل.
          سنفتحهما بعد استقرار خطّ الإنتاج الحالي وقياس زمن التوليد على أحجام
          حقيقية.
        </p>

        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          {ITEMS.map((item) => (
            <Panel key={item.title} className="p-6">
              <div className="mono text-xs tracking-widest text-accent">
                PHASE 2
              </div>
              <h2 className="mt-3 text-lg font-semibold">{item.title}</h2>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                {item.body}
              </p>
              <ul className="mt-4 space-y-1.5 text-sm text-muted">
                {item.points.map((point) => (
                  <li key={point}>— {point}</li>
                ))}
              </ul>
            </Panel>
          ))}
        </div>
      </AppShell>
    </RequireAuth>
  );
}
