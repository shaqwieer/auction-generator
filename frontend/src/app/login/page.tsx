"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { landingFor, useAuth } from "@/components/shell";
import { Mono } from "@/components/ui";
import { ApiError, api, tokens } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) router.replace(landingFor(user));
  }, [user, router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      tokens.set(await api.login(email.trim(), password));
      router.replace(landingFor(await refresh()));
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "تعذّر الاتصال بالخادم.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      {/* Sample output as the visual: the product is a print pipeline. */}
      <aside className="relative hidden flex-col justify-between bg-ink p-12 text-white lg:flex">
        <div className="mono text-xs tracking-widest text-white/50">
          SAMPLE OUTPUT · BOOKLET-A4
        </div>
        <div className="flex items-end gap-5">
          {["03/120", "04/120"].map((label, index) => (
            <div
              key={label}
              className="relative aspect-[210/297] w-40 border border-white/20 bg-white/5"
              style={{ transform: `rotate(${index === 0 ? -3 : 2}deg)` }}
            >
              <span className="absolute right-0 top-0 h-4 w-px bg-white/40" />
              <span className="absolute right-0 top-0 h-px w-4 bg-white/40" />
              <span className="absolute bottom-0 left-0 h-4 w-px bg-white/40" />
              <span className="absolute bottom-0 left-0 h-px w-4 bg-white/40" />
              <span className="mono absolute bottom-3 left-0 right-0 text-center text-sm text-white/70">
                {label}
              </span>
            </div>
          ))}
        </div>
        <div className="mono text-xs text-white/50">
          120 ROWS → 121 PAGES · 00:38
        </div>
      </aside>

      <main className="flex items-center justify-center px-6 py-16">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5">
            <span aria-hidden className="relative h-6 w-6 border border-accent">
              <span className="absolute inset-[5px] block bg-accent" />
            </span>
            <span className="text-lg font-semibold">مطبعة</span>
          </div>

          <h1 className="text-2xl font-semibold">أهلًا بك من جديد</h1>
          <p className="mt-3 text-md leading-relaxed text-muted">
            ارفع ملف Excel واحصل على ملف PDF جاهز للطبع، دون فتح أي برنامج تصميم.
          </p>

          <form onSubmit={submit} className="mt-8 space-y-4">
            <div>
              <label className="field-label" htmlFor="email">
                البريد الإلكتروني
              </label>
              <input
                id="email"
                type="email"
                dir="ltr"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div>
              <label className="field-label" htmlFor="password">
                كلمة المرور
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>

            {error ? (
              <p className="border border-[#F3D6C6] bg-[#FDF2EC] px-3 py-2 text-sm text-bad">
                {error}
              </p>
            ) : null}

            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy ? "جارٍ الدخول…" : "تسجيل الدخول"}
              <span aria-hidden>←</span>
            </button>
          </form>

          <p className="mt-6 text-sm text-muted-soft">
            ليس لديك حساب؟ تواصل مع فريق مطبعة.
          </p>
          <p className="mt-8 text-xs text-muted-soft">
            حساب تجريبي: <Mono>noura@fahd-group.sa</Mono> · كلمة المرور{" "}
            <Mono>matbaa1234</Mono>
          </p>
        </div>
      </main>
    </div>
  );
}
