"use client";

import { useCallback, useEffect, useState } from "react";

import { AppShell, RequireAuth } from "@/components/shell";
import {
  Banner,
  Empty,
  Mono,
  Panel,
  PanelHeader,
  Row,
  Spinner,
  Table,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { ClientOut, UserOut } from "@/types/api";

const COLUMNS = "1.4fr 1.1fr 90px 90px 90px 150px";

export default function ClientsPage() {
  return (
    <RequireAuth staffOnly>
      <Clients />
    </RequireAuth>
  );
}

function Clients() {
  const [clients, setClients] = useState<ClientOut[] | null>(null);
  const [editing, setEditing] = useState<ClientOut | null>(null);
  const [creating, setCreating] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setClients(await api.clients());
    } catch {
      setClients([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function remove(client: ClientOut) {
    setError(null);
    setNote(null);
    try {
      await api.deleteClient(client.id);
      await load();
      setNote(
        client.project_count > 0
          ? `أُوقف «${client.name}» بدل حذفه — لديه ${client.project_count} مشروعًا وحذفه يمحو مخرجاتها.`
          : `حُذف «${client.name}».`,
      );
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "تعذّر الحذف.");
    }
  }

  return (
    <AppShell
      breadcrumb="لوحة المشرف / العملاء"
      action={
        <button
          type="button"
          className="btn-primary"
          onClick={() => {
            setEditing(null);
            setCreating(true);
          }}
        >
          إضافة عميل <span aria-hidden>←</span>
        </button>
      }
    >
      {error ? <Banner tone="error" title={error} /> : null}
      {note ? <Banner tone="info" title={note} /> : null}

      {creating || editing ? (
        <ClientForm
          client={editing}
          onCancel={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={async (created) => {
            setCreating(false);
            setEditing(null);
            setError(null);
            await load();
            if (created) setExpanded(created.id);
          }}
          onError={setError}
          onNote={setNote}
        />
      ) : null}

      <Panel className="mt-5">
        <PanelHeader
          title="العملاء"
          meta={clients ? `${clients.length} CLIENTS` : undefined}
        />
        {clients === null ? (
          <Spinner />
        ) : clients.length === 0 ? (
          <Empty title="لا يوجد عملاء بعد" hint="أضِف عميلًا لإسناد المشاريع إليه." />
        ) : (
          <Table
            columns={COLUMNS}
            head={[
              "العميل",
              "التواصل",
              <Mono key="p">PROJECTS</Mono>,
              <Mono key="u">LOGINS</Mono>,
              "الحالة",
              "",
            ]}
          >
            {clients.map((client) => (
              <div key={client.id}>
                <Row columns={COLUMNS}>
                  <div className="min-w-0">
                    <div className="truncate font-medium">{client.name}</div>
                    <div className="mono truncate text-xs text-muted-soft">
                      {client.code}
                    </div>
                  </div>
                  <span className="mono truncate text-xs text-muted">
                    {client.contact_email ?? client.contact_phone ?? "—"}
                  </span>
                  <Mono>{client.project_count}</Mono>
                  <span
                    className={
                      client.user_count === 0 ? "text-bad" : "text-muted"
                    }
                  >
                    <Mono>{client.user_count}</Mono>
                  </span>
                  <span
                    className={client.is_active ? "text-ok" : "text-muted-soft"}
                  >
                    {client.is_active ? "نشط" : "موقوف"}
                  </span>
                  <div className="flex items-center gap-3 text-xs">
                    <button
                      type="button"
                      className="text-accent hover:text-ink"
                      onClick={() =>
                        setExpanded(expanded === client.id ? null : client.id)
                      }
                    >
                      {expanded === client.id ? "إخفاء الحسابات" : "الحسابات"}
                    </button>
                    <button
                      type="button"
                      className="text-accent hover:text-ink"
                      onClick={() => {
                        setCreating(false);
                        setEditing(client);
                      }}
                    >
                      تحرير
                    </button>
                    {client.is_active ? (
                      <button
                        type="button"
                        className="text-muted-soft hover:text-bad"
                        onClick={() => void remove(client)}
                      >
                        {client.project_count > 0 ? "إيقاف" : "حذف"}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="text-muted-soft hover:text-ok"
                        onClick={async () => {
                          await api.updateClient(client.id, { is_active: true });
                          await load();
                        }}
                      >
                        تفعيل
                      </button>
                    )}
                  </div>
                </Row>
                {expanded === client.id ? (
                  <ClientUsers
                    client={client}
                    onChanged={load}
                    onError={setError}
                    onNote={setNote}
                  />
                ) : null}
              </div>
            ))}
          </Table>
        )}
      </Panel>
    </AppShell>
  );
}

/** The sign-ins attached to one client: list, add, reset, remove. */
function ClientUsers({
  client,
  onChanged,
  onError,
  onNote,
}: {
  client: ClientOut;
  onChanged: () => void | Promise<void>;
  onError: (message: string) => void;
  onNote: (message: string) => void;
}) {
  const [users, setUsers] = useState<UserOut[] | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      setUsers(await api.clientUsers(client.id));
    } catch {
      setUsers([]);
    }
  }, [client.id]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="border-b border-line bg-paper px-5 py-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-medium">
          حسابات الدخول لـ «{client.name}»
        </span>
        <button
          type="button"
          className="text-xs text-accent"
          onClick={() => setAdding((v) => !v)}
        >
          {adding ? "إلغاء" : "+ إضافة حساب"}
        </button>
      </div>

      {adding ? (
        <UserForm
          onCancel={() => setAdding(false)}
          onSubmit={async (values) => {
            await api.addClientUser(client.id, values);
            setAdding(false);
            await load();
            await onChanged();
            onNote(
              `أُنشئ الحساب «${values.email}» — سجّل الدخول به لتجربة حساب هذا العميل.`,
            );
          }}
          onError={onError}
        />
      ) : null}

      {users === null ? (
        <p className="text-sm text-muted-soft">جارٍ التحميل…</p>
      ) : users.length === 0 ? (
        <p className="text-sm text-bad">
          لا يوجد حساب دخول لهذا العميل — لن يستطيع أحد استخدامه.
        </p>
      ) : (
        <ul className="space-y-2">
          {users.map((user) => (
            <li
              key={user.id}
              className="flex flex-wrap items-center justify-between gap-3 border border-line bg-surface px-4 py-2.5"
            >
              <div className="min-w-0">
                <div className="truncate text-sm">{user.name}</div>
                <div className="mono truncate text-xs text-muted-soft">
                  {user.email} · {user.role}
                </div>
              </div>
              <div className="flex items-center gap-3 text-xs">
                <button
                  type="button"
                  className="text-accent hover:text-ink"
                  onClick={async () => {
                    const next = window.prompt(
                      `كلمة مرور جديدة لـ ${user.email} (8 أحرف على الأقل)`,
                    );
                    if (!next) return;
                    try {
                      await api.resetPassword(user.id, next);
                      onNote(`غُيّرت كلمة مرور «${user.email}».`);
                    } catch (caught) {
                      onError(
                        caught instanceof ApiError
                          ? caught.message
                          : "تعذّر تغيير كلمة المرور.",
                      );
                    }
                  }}
                >
                  كلمة المرور
                </button>
                <button
                  type="button"
                  className="text-muted-soft hover:text-bad"
                  onClick={async () => {
                    try {
                      await api.deleteUser(user.id);
                      await load();
                      await onChanged();
                    } catch (caught) {
                      onError(
                        caught instanceof ApiError
                          ? caught.message
                          : "تعذّر الحذف.",
                      );
                    }
                  }}
                >
                  حذف
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function UserForm({
  onCancel,
  onSubmit,
  onError,
}: {
  onCancel: () => void;
  onSubmit: (values: {
    name: string;
    email: string;
    password: string;
    role: "client" | "operator";
  }) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"client" | "operator">("client");
  const [busy, setBusy] = useState(false);

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        try {
          await onSubmit({
            name: name.trim(),
            email: email.trim().toLowerCase(),
            password,
            role,
          });
          setName("");
          setEmail("");
          setPassword("");
        } catch (caught) {
          onError(
            caught instanceof ApiError ? caught.message : "تعذّر إنشاء الحساب.",
          );
        } finally {
          setBusy(false);
        }
      }}
      className="mb-4 grid gap-3 border border-line bg-surface p-4 sm:grid-cols-4"
    >
      <div>
        <span className="field-label">الاسم *</span>
        <input required value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div>
        <span className="field-label">البريد *</span>
        <input
          required
          type="email"
          dir="ltr"
          className="mono text-xs"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div>
        <span className="field-label">كلمة المرور *</span>
        <input
          required
          minLength={8}
          dir="ltr"
          className="mono text-xs"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="8 أحرف على الأقل"
        />
      </div>
      <div>
        <span className="field-label">الدور</span>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as "client" | "operator")}
        >
          <option value="client">عميل</option>
          <option value="operator">مشغّل</option>
        </select>
      </div>
      <div className="flex gap-2 sm:col-span-4">
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? "جارٍ الإنشاء…" : "إنشاء الحساب"}
        </button>
        <button type="button" className="btn-ghost" onClick={onCancel}>
          إلغاء
        </button>
      </div>
      <p className="text-xs text-muted-soft sm:col-span-4">
        كلمة المرور تُحفظ مُجزَّأة ولا يمكن استرجاعها لاحقًا — دوّنها الآن أو
        غيّرها متى شئت.
      </p>
    </form>
  );
}

function ClientForm({
  client,
  onCancel,
  onSaved,
  onError,
  onNote,
}: {
  client: ClientOut | null;
  onCancel: () => void;
  onSaved: (created: ClientOut | null) => void | Promise<void>;
  onError: (message: string) => void;
  onNote: (message: string) => void;
}) {
  const [name, setName] = useState(client?.name ?? "");
  const [code, setCode] = useState(client?.code ?? "");
  const [email, setEmail] = useState(client?.contact_email ?? "");
  const [phone, setPhone] = useState(client?.contact_phone ?? "");
  const [withLogin, setWithLogin] = useState(!client);
  const [userName, setUserName] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [userPassword, setUserPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      if (client) {
        await api.updateClient(client.id, {
          name: name.trim(),
          contact_email: email.trim() || null,
          contact_phone: phone.trim() || null,
        });
        await onSaved(null);
        return;
      }
      const created = await api.createClient({
        name: name.trim(),
        code: code.trim().toUpperCase(),
        contact_email: email.trim() || null,
        contact_phone: phone.trim() || null,
        ...(withLogin
          ? {
              user: {
                name: userName.trim(),
                email: userEmail.trim().toLowerCase(),
                password: userPassword,
              },
            }
          : {}),
      });
      if (withLogin) {
        onNote(
          `أُنشئ العميل وحساب الدخول «${userEmail.trim().toLowerCase()}» — سجّل الخروج ثم ادخل به لتجربة حسابه.`,
        );
      }
      await onSaved(created);
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "تعذّر الحفظ.");
      setBusy(false);
    }
  }

  return (
    <Panel className="mt-5">
      <PanelHeader title={client ? `تحرير: ${client.name}` : "عميل جديد"} />
      <form onSubmit={submit} className="grid gap-4 p-5 sm:grid-cols-2">
        <div>
          <label className="field-label" htmlFor="cname">
            اسم العميل *
          </label>
          <input
            id="cname"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div>
          <label className="field-label" htmlFor="ccode">
            الرمز *
          </label>
          <input
            id="ccode"
            dir="ltr"
            required
            className="mono"
            value={code}
            disabled={Boolean(client)}
            placeholder="AAYAN"
            onChange={(e) => setCode(e.target.value)}
          />
          {client ? (
            <p className="mt-1 text-xs text-muted-soft">
              الرمز هوية ثابتة — لا يتغيّر بعد الإنشاء.
            </p>
          ) : null}
        </div>
        <div>
          <label className="field-label" htmlFor="cmail">
            بريد التواصل
          </label>
          <input
            id="cmail"
            type="email"
            dir="ltr"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div>
          <label className="field-label" htmlFor="cphone">
            الجوال
          </label>
          <input
            id="cphone"
            dir="ltr"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </div>

        {client ? null : (
          <div className="border-t border-line pt-4 sm:col-span-2">
            <label className="flex items-center gap-2 text-md font-medium">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={withLogin}
                onChange={(e) => setWithLogin(e.target.checked)}
              />
              أنشئ حساب دخول لهذا العميل
            </label>
            <p className="mt-1.5 text-sm text-muted">
              يُنشأ مع العميل في عملية واحدة — استخدمه لتسجيل الدخول وتجربة
              حسابه بنفسك.
            </p>

            {withLogin ? (
              <div className="mt-4 grid gap-4 sm:grid-cols-3">
                <div>
                  <label className="field-label" htmlFor="uname">
                    اسم المستخدم *
                  </label>
                  <input
                    id="uname"
                    required={withLogin}
                    value={userName}
                    placeholder="نورة الحربي"
                    onChange={(e) => setUserName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="field-label" htmlFor="uemail">
                    البريد *
                  </label>
                  <input
                    id="uemail"
                    required={withLogin}
                    type="email"
                    dir="ltr"
                    className="mono text-xs"
                    value={userEmail}
                    placeholder="user@client.sa"
                    onChange={(e) => setUserEmail(e.target.value)}
                  />
                </div>
                <div>
                  <label className="field-label" htmlFor="upass">
                    كلمة المرور *
                  </label>
                  <input
                    id="upass"
                    required={withLogin}
                    minLength={8}
                    dir="ltr"
                    className="mono text-xs"
                    value={userPassword}
                    placeholder="8 أحرف على الأقل"
                    onChange={(e) => setUserPassword(e.target.value)}
                  />
                </div>
                <p className="text-xs text-muted-soft sm:col-span-3">
                  كلمة المرور تُحفظ مُجزَّأة ولا يمكن عرضها لاحقًا — دوّنها الآن،
                  أو غيّرها من قائمة الحسابات متى شئت.
                </p>
              </div>
            ) : null}
          </div>
        )}

        <div className="flex gap-2 sm:col-span-2">
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? "جارٍ الحفظ…" : client ? "حفظ" : "إنشاء العميل"}
          </button>
          <button type="button" className="btn-ghost" onClick={onCancel}>
            إلغاء
          </button>
        </div>
      </form>
    </Panel>
  );
}
