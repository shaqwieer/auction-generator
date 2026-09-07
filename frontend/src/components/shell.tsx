/**
 * The application chrome: a dark sidebar pinned to the right, and a top bar
 * carrying the breadcrumb with the primary action on the left.
 */
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { AuthImage } from "@/components/ui";
import { API_URL, api, tokens } from "@/lib/api";
import type { UserOut } from "@/types/api";

interface AuthState {
  user: UserOut | null;
  loading: boolean;
  signOut: () => void;
  refresh: () => Promise<UserOut | null>;
}

const AuthContext = createContext<AuthState>({
  user: null,
  loading: true,
  signOut: () => undefined,
  refresh: async () => null,
});

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const refresh = useCallback(async (): Promise<UserOut | null> => {
    if (!tokens.access()) {
      setUser(null);
      setLoading(false);
      return null;
    }
    try {
      const me = await api.me();
      setUser(me);
      return me;
    } catch {
      tokens.clear();
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const signOut = useCallback(() => {
    tokens.clear();
    setUser(null);
    router.replace("/login");
  }, [router]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo(
    () => ({ user, loading, signOut, refresh }),
    [user, loading, signOut, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Where a session belongs after sign-in.
 *
 * An admin's sidebar carries only the admin block, so dropping them on the
 * client dashboard would leave nothing lit and nothing to click back to.
 */
export function landingFor(user: UserOut | null): string {
  return user?.role === "admin" ? "/admin" : "/";
}

interface NavItem {
  href: string;
  label: string;
  staffOnly?: boolean;
}

const CLIENT_NAV: NavItem[] = [
  { href: "/", label: "الرئيسية" },
  // Neither "بيانات الشركة" nor "مشروع جديد" is here. The first is what the
  // company block at the top of the sidebar already links to; the second is the
  // primary action in the top bar. Both, listed again here, put two entries on
  // the same route and lit them both.
  { href: "/projects", label: "مشاريعي" },
  { href: "/archive", label: "أرشيف المخرجات" },
];

const ADMIN_NAV: NavItem[] = [
  { href: "/admin", label: "لوحة المشرف", staffOnly: true },
  { href: "/admin/templates", label: "القوالب", staffOnly: true },
  { href: "/admin/categories", label: "التصنيفات", staffOnly: true },
  { href: "/admin/clients", label: "العملاء", staffOnly: true },
  { href: "/admin/ops", label: "مراقب العمليات", staffOnly: true },
  { href: "/admin/settings", label: "الإعدادات والصلاحيات", staffOnly: true },
  { href: "/admin/soon", label: "قريبًا", staffOnly: true },
];

/**
 * Whether a nav href covers the current path at all.
 *
 * "/" is exact-only; every other entry also owns its sub-paths, so
 * /projects/abc/mapping still lights up "مشاريعي".
 */
function covers(href: string, pathname: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The single active entry: the longest href that covers the path.
 *
 * A plain prefix test lights up two items at once — /projects/new is covered by
 * both "مشاريعي" and "مشروع جديد" — so the most specific match wins.
 */
function activeHref(items: NavItem[], pathname: string): string | null {
  const hits = items.map((i) => i.href).filter((h) => covers(h, pathname));
  if (hits.length === 0) return null;
  return hits.reduce((best, href) => (href.length > best.length ? href : best));
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      className={`block rounded px-3 py-2 text-base transition-colors ${
        active
          ? "bg-white/10 text-white"
          : "text-white/70 hover:bg-white/5 hover:text-white"
      }`}
    >
      {item.label}
    </Link>
  );
}

export function AppShell({
  breadcrumb,
  action,
  children,
}: {
  breadcrumb: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const { user, signOut } = useAuth();
  const isAdmin = user?.role === "admin";
  const isStaff = isAdmin || user?.role === "operator";

  // An admin runs the platform, not a booklet: the client screens stay reachable
  // by URL, but they are not the admin's workspace and are not in the sidebar.
  // An operator works in both, so they keep both blocks.
  const clientItems = isAdmin ? [] : CLIENT_NAV;
  const adminItems = isStaff ? ADMIN_NAV : [];

  const active = activeHref([...clientItems, ...adminItems], pathname);
  const isActive = (href: string): boolean => href === active;

  return (
    <div className="flex min-h-screen bg-paper">
      <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col overflow-y-auto bg-ink py-5 text-white md:flex">
        <div className="border-b border-white/10 px-5 pb-5">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden
              className="relative h-6 w-6 shrink-0 border border-accent"
            >
              <span className="absolute inset-[5px] block bg-accent" />
            </span>
            <span>
              <span className="block text-lg font-semibold leading-tight">
                مطبعة
              </span>
              <span className="mono block text-[10px] tracking-widest text-white/50">
                PRINT AUTOMATION
              </span>
            </span>
          </div>
        </div>

        {/*
          Whose booklets these are. The company's own mark went into the product
          the moment it went into the booklet: a client filling a page needs to
          see, without looking for it, which company the pages will be branded
          for — an agency running three of them will otherwise brand one with
          another's name.
        */}
        {user?.company ? (
          <Link
            href="/company"
            className="mx-3 mt-4 flex items-center gap-3 border border-white/10 px-3 py-3 transition-colors hover:border-white/25"
          >
            {user.company.logo_filename ? (
              <AuthImage
                src={`${API_URL}/api/v1/company/logo`}
                alt={user.company.name}
                className="h-8 w-8 shrink-0 object-contain"
              />
            ) : (
              <span
                aria-hidden
                className="grid h-8 w-8 shrink-0 place-items-center border border-white/20 text-xs text-white/70"
              >
                {user.company.name.trim().slice(0, 1) || "؟"}
              </span>
            )}
            <span className="min-w-0">
              <span className="block truncate text-sm leading-tight">
                {user.company.name}
              </span>
              <span className="mono block text-[10px] tracking-widest text-white/40">
                {user.company.code}
              </span>
            </span>
          </Link>
        ) : null}

        <nav className="flex-1 space-y-1 px-3 pt-4">
          {clientItems.map((item) => (
            <NavLink key={item.href} item={item} active={isActive(item.href)} />
          ))}
          {adminItems.length > 0 ? (
            <>
              {/* The label separates the two blocks; with nothing above it, the
                  separating space is what goes, not the label. */}
              <div
                className={`mono px-3 pb-1 text-[10px] tracking-widest text-white/40 ${
                  clientItems.length > 0 ? "pt-5" : ""
                }`}
              >
                ADMIN
              </div>
              {adminItems.map((item) => (
                <NavLink key={item.href} item={item} active={isActive(item.href)} />
              ))}
            </>
          ) : null}
        </nav>

        <div className="border-t border-white/10 px-5 pt-4">
          <div className="text-base">{user?.name ?? "—"}</div>
          <div className="mono truncate text-[11px] text-white/50">
            {user?.email ?? ""}
          </div>
          <button
            type="button"
            onClick={signOut}
            className="mt-3 text-sm text-white/60 hover:text-accent"
          >
            تسجيل الخروج
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex min-h-[60px] flex-wrap items-center justify-between gap-3 border-b border-line bg-paper/95 px-6 py-3 backdrop-blur">
          <div className="text-base text-muted">{breadcrumb}</div>
          {action}
        </header>
        <main className="flex-1 px-6 py-6">{children}</main>
      </div>
    </div>
  );
}

/** Redirects to the sign-in screen when there is no session. */
export function RequireAuth({
  children,
  staffOnly = false,
}: {
  children: ReactNode;
  staffOnly?: boolean;
}) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/login");
    else if (staffOnly && user.role === "client") router.replace("/");
  }, [user, loading, staffOnly, router]);

  if (loading || !user) {
    return (
      <div className="grid min-h-screen place-items-center text-sm text-muted-soft">
        جارٍ التحقّق من الجلسة…
      </div>
    );
  }
  if (staffOnly && user.role === "client") return null;
  return <>{children}</>;
}
